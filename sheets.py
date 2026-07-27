# sheets.py
"""
گوگل شیٹس کو بطور ڈیٹا بیس استعمال کرنے والی مرکزی فائل۔

اہم ذمہ داریاں:
    1) Google Sheets کے ساتھ محفوظ رابطہ قائم کرنا
    2) تمام ضروری Worksheets خودکار طور پر بنانا
    3) پرانی Worksheets میں نئے کالم محفوظ طریقے سے شامل کرنا
    4) Users، Students، Attendance، DailyWork، Logs اور Settings کا ڈیٹا سنبھالنا
    5) صبح/دوپہر کی حاضری کے الگ ریکارڈ محفوظ کرنا
    6) سبق، سبقی، منزل اور پاؤ کا روزانہ تعلیمی ریکارڈ محفوظ کرنا

طالب علم کی شناخت:
    StudentName + FatherName + AssignedTeacher

حاضری کی منفرد شناخت:
    Date + AttendanceSession + StudentName + FatherName

روزانہ تعلیمی کام کی منفرد شناخت:
    Date + StudentName + FatherName
"""

from __future__ import annotations

import string
import time
from pathlib import Path
from typing import Any, Iterable, Callable

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

import config
from utils import hash_password


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


MAX_API_RETRIES = 5
INITIAL_RETRY_DELAY_SECONDS = 1.5
DATA_CACHE_TTL_SECONDS = 60


def _is_rate_limit_error(error: Exception) -> bool:
    """چیک کریں کہ خرابی Google API کی 429 rate-limit خرابی ہے۔"""
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)

    if status_code == 429:
        return True

    message = str(error).lower()
    return (
        "429" in message
        or "quota exceeded" in message
        or "rate limit" in message
        or "too many requests" in message
    )


def _call_with_retry(
    operation: Callable[[], Any],
    action_desc: str,
):
    """
    Google API کی عارضی 429 خرابی پر exponential backoff کے ساتھ دوبارہ کوشش کریں۔
    """
    delay = INITIAL_RETRY_DELAY_SECONDS
    last_error: Exception | None = None

    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            return operation()
        except Exception as error:
            last_error = error

            if not _is_rate_limit_error(error) or attempt == MAX_API_RETRIES:
                raise

            time.sleep(delay)
            delay *= 2

    raise RuntimeError(
        f"{action_desc} مکمل نہیں ہو سکا۔"
    ) from last_error


def clear_data_cache() -> None:
    """Google Sheets سے پڑھے گئے عارضی cached data کو صاف کریں۔"""
    _read_all_records_cached.clear()


# ==================================================
# عمومی مددگار فنکشنز
# ==================================================
def _clean(value: Any) -> str:
    """کسی بھی قدر کو صاف متن میں تبدیل کریں۔"""
    if value is None:
        return ""
    return str(value).strip()


def _normalise(value: Any) -> str:
    """موازنہ کے لیے متن کو یکساں شکل میں تبدیل کریں۔"""
    return _clean(value).casefold()



def _date_key(value: Any) -> str:
    """مختلف Google Sheets date formats کو YYYY-MM-DD میں یکساں کریں۔"""
    cleaned = _clean(value)
    if not cleaned:
        return ""

    try:
        parsed = pd.to_datetime(cleaned, errors="raise")
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        return cleaned


def _column_letter(column_number: int) -> str:
    """1-based کالم نمبر کو Google Sheets کے حرف میں تبدیل کریں۔"""
    if column_number < 1:
        raise ValueError("کالم نمبر کم از کم 1 ہونا چاہیے۔")

    letters = ""
    number = column_number

    while number:
        number, remainder = divmod(number - 1, 26)
        letters = string.ascii_uppercase[remainder] + letters

    return letters


def _row_for_actual_headers(
    worksheet,
    values_by_header: dict[str, Any],
    required_headers: list[str],
) -> list[Any]:
    """
    Worksheet کی حقیقی header ترتیب کے مطابق row تیار کریں۔

    پرانی sheets میں کالموں کی ترتیب config سے مختلف ہو سکتی ہے۔
    اس helper کے بغیر append_row values غلط کالموں میں جا سکتی ہیں۔
    """
    actual_headers = _call_with_retry(
        lambda: worksheet.row_values(1),
        f"'{worksheet.title}' کے headers پڑھنے",
    )

    if not actual_headers:
        actual_headers = list(required_headers)

    missing = [
        header for header in required_headers
        if header not in actual_headers
    ]
    if missing:
        raise ValueError(
            "Worksheet میں مطلوبہ headers موجود نہیں: "
            + ", ".join(missing)
        )

    return [
        values_by_header.get(header, "")
        for header in actual_headers
    ]


def _dataframe_with_headers(
    records: list[dict],
    headers: list[str],
) -> pd.DataFrame:
    """
    DataFrame بنائیں اور تمام مطلوبہ کالم یقینی بنائیں۔
    اضافی کالم برقرار رکھے جاتے ہیں۔
    """
    df = pd.DataFrame(records)

    if df.empty:
        return pd.DataFrame(columns=headers)

    for header in headers:
        if header not in df.columns:
            df[header] = ""

    ordered_columns = headers + [
        column for column in df.columns if column not in headers
    ]
    return df[ordered_columns]


def _unique_non_empty(values: Iterable[Any]) -> list[str]:
    """خالی قدروں کو نکال کر منفرد متن واپس کریں۔"""
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        cleaned = _clean(value)
        key = _normalise(cleaned)
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)

    return result


# ==================================================
# Google Sheets Authentication
# ==================================================
@st.cache_resource(show_spinner=False)
def get_client():
    """
    Google Sheets کے لیے gspread client تیار کریں۔

    Streamlit Cloud پر st.secrets["gcp_service_account"] استعمال ہوتا ہے۔
    مقامی کمپیوٹر پر credentials.json استعمال ہوتی ہے۔
    """
    try:
        credentials = None

        try:
            service_account_info = dict(st.secrets["gcp_service_account"])
            credentials = Credentials.from_service_account_info(
                service_account_info,
                scopes=SCOPES,
            )
        except Exception:
            credentials_path = Path(config.CREDENTIALS_FILE)

            if not credentials_path.exists():
                st.error(
                    "⚠️ credentials.json فائل نہیں ملی۔\n\n"
                    f"متوقع جگہ: {credentials_path.resolve()}"
                )
                st.stop()

            credentials = Credentials.from_service_account_file(
                str(credentials_path),
                scopes=SCOPES,
            )

        return gspread.authorize(credentials)

    except Exception as error:
        st.error("⚠️ گوگل شیٹس کے ساتھ رابطہ قائم نہیں ہو سکا۔")
        st.exception(error)
        st.stop()


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    """مرکزی Google Spreadsheet کھولیں یا موجود نہ ہونے پر بنائیں۔"""
    client = get_client()

    try:
        return _call_with_retry(
            lambda: client.open(config.GOOGLE_SHEET_NAME),
            "گوگل اسپریڈشیٹ کھولنے",
        )

    except gspread.SpreadsheetNotFound:
        try:
            return _call_with_retry(
                lambda: client.create(config.GOOGLE_SHEET_NAME),
                "نئی گوگل اسپریڈشیٹ بنانے",
            )
        except Exception as error:
            st.error(
                "⚠️ نئی گوگل اسپریڈشیٹ نہیں بنائی جا سکی۔ "
                "سروس اکاؤنٹ کی Drive اجازتیں چیک کریں۔"
                f"\n\nتفصیل: {error}"
            )
            st.stop()

    except Exception as error:
        st.error(
            "⚠️ گوگل اسپریڈشیٹ کھولنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        st.stop()


def clear_cache():
    """محفوظ شدہ connection اور پڑھے گئے data دونوں صاف کریں۔"""
    clear_data_cache()
    get_client.clear()
    get_spreadsheet.clear()


# ==================================================
# Worksheet بنانا اور headers ہم آہنگ کرنا
# ==================================================
def _sync_headers(worksheet, headers: list[str]) -> None:
    """
    پرانی Worksheet میں نئے مطلوبہ کالم شامل کریں۔

    موجودہ کالموں اور ڈیٹا کو حذف یا ترتیب سے نہیں ہٹایا جاتا۔
    نئے کالم آخر میں شامل ہوتے ہیں تاکہ پرانے ریکارڈ محفوظ رہیں۔
    """
    try:
        first_row = _call_with_retry(
            lambda: worksheet.row_values(1),
            f"'{worksheet.title}' کے headers پڑھنے",
        )

        if not first_row:
            _call_with_retry(
                lambda: worksheet.update(
                    range_name=f"A1:{_column_letter(len(headers))}1",
                    values=[headers],
                ),
                f"'{worksheet.title}' کے headers لکھنے",
            )
            return

        missing_headers = [
            header for header in headers if header not in first_row
        ]

        if not missing_headers:
            return

        required_column_count = len(first_row) + len(missing_headers)
        if worksheet.col_count < required_column_count:
            _call_with_retry(
                lambda: worksheet.resize(cols=required_column_count),
                f"'{worksheet.title}' کے کالم بڑھانے",
            )

        start_column = len(first_row) + 1
        end_column = required_column_count

        _call_with_retry(
            lambda: worksheet.update(
                range_name=(
                    f"{_column_letter(start_column)}1:"
                    f"{_column_letter(end_column)}1"
                ),
                values=[missing_headers],
            ),
            f"'{worksheet.title}' کے نئے headers لکھنے",
        )

    except Exception as error:
        st.error(
            f"⚠️ '{worksheet.title}' کے کالم ہم آہنگ نہیں کیے جا سکے۔"
            f"\n\nتفصیل: {error}"
        )
        st.stop()


def _get_or_create_worksheet(
    sheet_name: str,
    headers: list[str],
):
    """Worksheet حاصل کریں، بنائیں، اور اس کے headers مکمل کریں۔"""
    spreadsheet = get_spreadsheet()

    try:
        worksheet = _call_with_retry(
            lambda: spreadsheet.worksheet(sheet_name),
            f"'{sheet_name}' ورک شیٹ کھولنے",
        )

    except gspread.WorksheetNotFound:
        try:
            worksheet = _call_with_retry(
                lambda: spreadsheet.add_worksheet(
                    title=sheet_name,
                    rows=1000,
                    cols=max(len(headers), 5),
                ),
                f"'{sheet_name}' ورک شیٹ بنانے",
            )
            _call_with_retry(
                lambda: worksheet.append_row(
                    headers,
                    value_input_option="RAW",
                ),
                f"'{sheet_name}' کے headers شامل کرنے",
            )
            return worksheet

        except Exception as error:
            st.error(
                f"⚠️ '{sheet_name}' ورک شیٹ نہیں بنائی جا سکی۔"
                f"\n\nتفصیل: {error}"
            )
            st.stop()

    except Exception as error:
        st.error(
            f"⚠️ '{sheet_name}' ورک شیٹ تک رسائی نہیں ہو سکی۔"
            f"\n\nتفصیل: {error}"
        )
        st.stop()

    _sync_headers(worksheet, headers)
    return worksheet


def initialize_database():
    """
    تمام مطلوبہ Worksheets بنائیں۔

    Users Worksheet خالی ہونے پر ابتدائی صارفین شامل کیے جاتے ہیں۔
    DailyWork Worksheet بھی خودکار طور پر بنائی جاتی ہے۔
    """
    users_ws = _get_or_create_worksheet(
        config.SHEET_USERS,
        config.USERS_HEADERS,
    )

    _get_or_create_worksheet(
        config.SHEET_STUDENTS,
        config.STUDENTS_HEADERS,
    )
    _get_or_create_worksheet(
        config.SHEET_ATTENDANCE,
        config.ATTENDANCE_HEADERS,
    )
    _get_or_create_worksheet(
        config.SHEET_DAILY_WORK,
        config.DAILY_WORK_HEADERS,
    )
    _get_or_create_worksheet(
        config.SHEET_LOGS,
        config.LOGS_HEADERS,
    )
    _get_or_create_worksheet(
        config.SHEET_SETTINGS,
        config.SETTINGS_HEADERS,
    )

    try:
        records = _call_with_retry(
            lambda: users_ws.get_all_records(),
            "صارفین کی ورک شیٹ پڑھنے",
        )
    except Exception as error:
        st.error(
            "⚠️ صارفین کی ورک شیٹ پڑھنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        st.stop()

    if records:
        return

    rows = [
        [
            _clean(user.get("Username")),
            hash_password(_clean(user.get("Password"))),
            _clean(user.get("FullName")),
            _clean(user.get("Role")),
            "TRUE",
        ]
        for user in config.DEFAULT_USERS
    ]

    _append_rows(users_ws, rows, "ابتدائی صارفین شامل کرنے")


# ==================================================
# عمومی CRUD فنکشنز
# ==================================================
@st.cache_data(
    ttl=DATA_CACHE_TTL_SECONDS,
    show_spinner=False,
)
def _read_all_records_cached(
    sheet_name: str,
    headers_tuple: tuple[str, ...],
) -> pd.DataFrame:
    """
    ایک ہی Streamlit rerun میں بار بار Google Sheets API call سے بچنے کے لیے
    مکمل worksheet data کو مختصر وقت کے لیے cache کریں۔
    """
    headers = list(headers_tuple)
    worksheet = _get_or_create_worksheet(sheet_name, headers)
    records = _call_with_retry(
        lambda: worksheet.get_all_records(),
        f"'{sheet_name}' سے ڈیٹا پڑھنے",
    )
    return _dataframe_with_headers(records, headers)


def read_all_records(
    sheet_name: str,
    headers: list[str],
) -> pd.DataFrame:
    """Worksheet کا مکمل ڈیٹا cache اور 429 retry کے ساتھ پڑھیں۔"""
    try:
        return _read_all_records_cached(
            sheet_name,
            tuple(headers),
        ).copy()
    except Exception as error:
        st.error(
            f"⚠️ '{sheet_name}' سے ڈیٹا پڑھنے میں خرابی پیش آئی۔"
            f"\\n\\nتفصیل: {error}"
        )
        return pd.DataFrame(columns=headers)


def _append_row(
    worksheet,
    row: list,
    action_desc: str = "ڈیٹا شامل کرنے",
) -> bool:
    try:
        _call_with_retry(
            lambda: worksheet.append_row(
                row,
                value_input_option="RAW",
            ),
            action_desc,
        )
        clear_data_cache()
        return True
    except Exception as error:
        st.error(
            f"⚠️ {action_desc} میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return False


def _append_rows(
    worksheet,
    rows: list[list],
    action_desc: str = "ڈیٹا شامل کرنے",
) -> bool:
    try:
        if rows:
            _call_with_retry(
                lambda: worksheet.append_rows(
                    rows,
                    value_input_option="RAW",
                ),
                action_desc,
            )
            clear_data_cache()
        return True
    except Exception as error:
        st.error(
            f"⚠️ {action_desc} میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return False


def _update_cell(
    worksheet,
    row: int,
    column: int,
    value: Any,
    action_desc: str = "ڈیٹا تبدیل کرنے",
) -> bool:
    try:
        _call_with_retry(
            lambda: worksheet.update_cell(row, column, value),
            action_desc,
        )
        clear_data_cache()
        return True
    except Exception as error:
        st.error(
            f"⚠️ {action_desc} میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return False


def _update_row_range(
    worksheet,
    row: int,
    values: list,
    action_desc: str = "ڈیٹا تبدیل کرنے",
) -> bool:
    try:
        last_column = _column_letter(len(values))
        _call_with_retry(
            lambda: worksheet.update(
                values=[values],
                range_name=f"A{row}:{last_column}{row}",
            ),
            action_desc,
        )
        clear_data_cache()
        return True
    except Exception as error:
        st.error(
            f"⚠️ {action_desc} میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return False


def _delete_row(
    worksheet,
    row: int,
    action_desc: str = "ڈیٹا حذف کرنے",
) -> bool:
    try:
        _call_with_retry(
            lambda: worksheet.delete_rows(row),
            action_desc,
        )
        clear_data_cache()
        return True
    except Exception as error:
        st.error(
            f"⚠️ {action_desc} میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return False


def worksheet_to_df(
    sheet_name: str,
    headers: list[str],
) -> pd.DataFrame:
    """پرانے کوڈ کے لیے ہم آہنگ نام۔"""
    return read_all_records(sheet_name, headers)


# ==================================================
# Users
# ==================================================
def get_all_users() -> pd.DataFrame:
    return read_all_records(config.SHEET_USERS, config.USERS_HEADERS)


def get_user(username: str):
    df = get_all_users()

    if df.empty or "Username" not in df.columns:
        return None

    match = df[
        df["Username"].astype(str).map(_normalise)
        == _normalise(username)
    ]

    if match.empty:
        return None

    return match.iloc[0].to_dict()


def add_user(
    username: str,
    password: str,
    fullname: str,
    role: str,
) -> bool:
    worksheet = _get_or_create_worksheet(
        config.SHEET_USERS,
        config.USERS_HEADERS,
    )

    if get_user(username) is not None:
        st.error("⚠️ یہ صارف نام پہلے سے موجود ہے۔")
        return False

    return _append_row(
        worksheet,
        [
            _clean(username),
            hash_password(password),
            _clean(fullname),
            _clean(role),
            "TRUE",
        ],
        "نیا صارف شامل کرنے",
    )


def _find_user_row(username: str):
    worksheet = _get_or_create_worksheet(
        config.SHEET_USERS,
        config.USERS_HEADERS,
    )

    try:
        records = _call_with_retry(
            lambda: worksheet.get_all_records(),
            "ورک شیٹ کا ڈیٹا پڑھنے",
        )
    except Exception as error:
        st.error(
            "⚠️ صارف تلاش کرنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return worksheet, None

    target = _normalise(username)

    for index, record in enumerate(records):
        if _normalise(record.get("Username")) == target:
            return worksheet, index + 2

    return worksheet, None


def update_user_password(username: str, new_password: str) -> bool:
    worksheet, row_number = _find_user_row(username)

    if row_number is None:
        st.error("⚠️ صارف نہیں ملا۔")
        return False

    return _update_cell(
        worksheet,
        row_number,
        config.USERS_HEADERS.index("PasswordHash") + 1,
        hash_password(new_password),
        "پاس ورڈ تبدیل کرنے",
    )


def update_user_info(
    username: str,
    fullname: str | None = None,
    active: bool | None = None,
) -> bool:
    worksheet, row_number = _find_user_row(username)

    if row_number is None:
        st.error("⚠️ صارف نہیں ملا۔")
        return False

    success = True

    if fullname is not None:
        success = _update_cell(
            worksheet,
            row_number,
            config.USERS_HEADERS.index("FullName") + 1,
            _clean(fullname),
            "صارف کی معلومات تبدیل کرنے",
        ) and success

    if active is not None:
        success = _update_cell(
            worksheet,
            row_number,
            config.USERS_HEADERS.index("Active") + 1,
            "TRUE" if active else "FALSE",
            "صارف کی حیثیت تبدیل کرنے",
        ) and success

    return success


def delete_user(username: str) -> bool:
    worksheet, row_number = _find_user_row(username)

    if row_number is None:
        st.error("⚠️ صارف نہیں ملا۔")
        return False

    return _delete_row(worksheet, row_number, "صارف حذف کرنے")


# ==================================================
# Students
# ==================================================
def get_all_students() -> pd.DataFrame:
    return read_all_records(
        config.SHEET_STUDENTS,
        config.STUDENTS_HEADERS,
    )


def get_active_students() -> pd.DataFrame:
    df = get_all_students()

    if df.empty or "Status" not in df.columns:
        return df

    return df[
        df["Status"].astype(str).str.strip()
        == config.STUDENT_STATUS_ACTIVE
    ].copy()


def get_students_for_teacher(assigned_teacher: str) -> pd.DataFrame:
    """منتخب استاد کے فعال طلباء حاصل کریں۔"""
    df = get_active_students()

    if df.empty or "AssignedTeacher" not in df.columns:
        return df

    return df[
        df["AssignedTeacher"].astype(str).map(_normalise)
        == _normalise(assigned_teacher)
    ].copy()


def student_exists(
    student_name: str,
    father_name: str,
    assigned_teacher: str | None = None,
) -> bool:
    df = get_all_students()

    if df.empty:
        return False

    required_columns = {"StudentName", "FatherName"}
    if not required_columns.issubset(df.columns):
        return False

    match = (
        df["StudentName"].astype(str).map(_normalise)
        == _normalise(student_name)
    ) & (
        df["FatherName"].astype(str).map(_normalise)
        == _normalise(father_name)
    )

    if assigned_teacher is not None and "AssignedTeacher" in df.columns:
        match = match & (
            df["AssignedTeacher"].astype(str).map(_normalise)
            == _normalise(assigned_teacher)
        )

    return bool(match.any())


def add_student(
    name,
    father_name,
    assigned_teacher,
    age,
    phone,
    address,
    admission_date,
) -> bool:
    worksheet = _get_or_create_worksheet(
        config.SHEET_STUDENTS,
        config.STUDENTS_HEADERS,
    )

    if student_exists(name, father_name, assigned_teacher):
        st.error("⚠️ یہی طالب علم اسی استاد کے ساتھ پہلے سے موجود ہے۔")
        return False

    return _append_row(
        worksheet,
        [
            _clean(name),
            _clean(father_name),
            _clean(assigned_teacher),
            _clean(age),
            _clean(phone),
            _clean(address),
            _clean(admission_date),
            config.STUDENT_STATUS_ACTIVE,
        ],
        "نیا طالب علم شامل کرنے",
    )


def _find_student_row(
    student_name: str,
    father_name: str,
    assigned_teacher: str,
):
    worksheet = _get_or_create_worksheet(
        config.SHEET_STUDENTS,
        config.STUDENTS_HEADERS,
    )

    try:
        records = _call_with_retry(
            lambda: worksheet.get_all_records(),
            "ورک شیٹ کا ڈیٹا پڑھنے",
        )
    except Exception as error:
        st.error(
            "⚠️ طالب علم تلاش کرنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return worksheet, None

    for index, record in enumerate(records):
        if (
            _normalise(record.get("StudentName")) == _normalise(student_name)
            and _normalise(record.get("FatherName")) == _normalise(father_name)
            and _normalise(record.get("AssignedTeacher"))
            == _normalise(assigned_teacher)
        ):
            return worksheet, index + 2

    return worksheet, None


def update_student(
    original_name,
    original_father_name,
    original_assigned_teacher,
    name,
    father_name,
    assigned_teacher,
    age,
    phone,
    address,
    admission_date,
    status,
) -> bool:
    worksheet, row_number = _find_student_row(
        original_name,
        original_father_name,
        original_assigned_teacher,
    )

    if row_number is None:
        st.error("⚠️ طالب علم نہیں ملا۔")
        return False

    identity_changed = (
        _normalise(original_name) != _normalise(name)
        or _normalise(original_father_name) != _normalise(father_name)
        or _normalise(original_assigned_teacher)
        != _normalise(assigned_teacher)
    )

    if identity_changed and student_exists(
        name,
        father_name,
        assigned_teacher,
    ):
        st.error("⚠️ نئی معلومات کے ساتھ یہی طالب علم پہلے سے موجود ہے۔")
        return False

    return _update_row_range(
        worksheet,
        row_number,
        [
            _clean(name),
            _clean(father_name),
            _clean(assigned_teacher),
            _clean(age),
            _clean(phone),
            _clean(address),
            _clean(admission_date),
            _clean(status),
        ],
        "طالب علم کی معلومات تبدیل کرنے",
    )


def update_student_status(
    student_name,
    father_name,
    assigned_teacher,
    status,
) -> bool:
    worksheet, row_number = _find_student_row(
        student_name,
        father_name,
        assigned_teacher,
    )

    if row_number is None:
        st.error("⚠️ طالب علم نہیں ملا۔")
        return False

    return _update_cell(
        worksheet,
        row_number,
        config.STUDENTS_HEADERS.index("Status") + 1,
        _clean(status),
        "طالب علم کی حیثیت تبدیل کرنے",
    )


def delete_student(
    student_name,
    father_name,
    assigned_teacher,
) -> bool:
    worksheet, row_number = _find_student_row(
        student_name,
        father_name,
        assigned_teacher,
    )

    if row_number is None:
        st.error("⚠️ طالب علم نہیں ملا۔")
        return False

    return _delete_row(worksheet, row_number, "طالب علم حذف کرنے")


# ==================================================
# Attendance
# ==================================================
def get_all_attendance() -> pd.DataFrame:
    """
    حاضری ہمیشہ تازہ Google Sheet سے پڑھیں۔

    Attendance form میں محفوظ کرنے کے فوراً بعد نئی rows دکھانا ضروری ہے،
    اس لیے اس مخصوص sheet پر عام 60-second data cache استعمال نہیں کیا جاتا۔
    429 سے بچاؤ کے لیے API retry بدستور فعال ہے۔
    """
    worksheet = _get_or_create_worksheet(
        config.SHEET_ATTENDANCE,
        config.ATTENDANCE_HEADERS,
    )

    try:
        records = _call_with_retry(
            lambda: worksheet.get_all_records(),
            "حاضری کی تازہ معلومات پڑھنے",
        )
        return _dataframe_with_headers(
            records,
            config.ATTENDANCE_HEADERS,
        )
    except Exception as error:
        st.error(
            "⚠️ حاضری کی تازہ معلومات پڑھنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return pd.DataFrame(columns=config.ATTENDANCE_HEADERS)


def attendance_exists_for_student(
    date: str,
    student_name: str,
    father_name: str,
    attendance_session: str | None = None,
) -> bool:
    """
    منتخب تاریخ اور سیشن میں طالب علم کی حاضری موجود ہونے کی جانچ کریں۔

    attendance_session نہ دینے پر پرانے کوڈ کے لیے اسی تاریخ کا
    کوئی بھی سیشن موجود ہو تو True واپس آتا ہے۔
    """
    df = get_all_attendance()

    if df.empty:
        return False

    required = {"Date", "StudentName", "FatherName"}
    if not required.issubset(df.columns):
        return False

    match = (
        df["Date"].map(_date_key) == _date_key(date)
    ) & (
        df["StudentName"].astype(str).map(_normalise)
        == _normalise(student_name)
    ) & (
        df["FatherName"].astype(str).map(_normalise)
        == _normalise(father_name)
    )

    if attendance_session is not None and "AttendanceSession" in df.columns:
        match = match & (
            df["AttendanceSession"].astype(str).map(_normalise)
            == _normalise(attendance_session)
        )

    return bool(match.any())


def attendance_exists_for_teacher(
    date: str,
    teacher_name: str,
    attendance_session: str | None = None,
) -> bool:
    """منتخب تاریخ، استاد اور اختیاری سیشن کا کوئی ریکارڈ چیک کریں۔"""
    df = get_all_attendance()

    if df.empty or not {"Date", "TeacherName"}.issubset(df.columns):
        return False

    match = (
        df["Date"].map(_date_key) == _date_key(date)
    ) & (
        df["TeacherName"].astype(str).map(_normalise)
        == _normalise(teacher_name)
    )

    if attendance_session is not None and "AttendanceSession" in df.columns:
        match = match & (
            df["AttendanceSession"].astype(str).map(_normalise)
            == _normalise(attendance_session)
        )

    return bool(match.any())


def submit_attendance(
    date: str,
    teacher_username: str,
    teacher_name: str,
    records: list[dict],
    attendance_session: str | None = None,
) -> bool:
    """
    کئی طلباء کی حاضری ایک ساتھ محفوظ کریں۔

    ترجیحی استعمال:
        submit_attendance(
            date,
            teacher_username,
            teacher_name,
            records,
            attendance_session,
        )

    records کی keys:
        StudentName
        FatherName
        Status

    پرانے کوڈ کی عارضی ہم آہنگی کے لیے اگر attendance_session الگ نہ دیا
    جائے تو ہر record کی AttendanceSession key پڑھی جائے گی۔
    """
    from utils import now_time_str

    if not records:
        return True

    prepared_records: list[dict] = []

    for record in records:
        session = _clean(
            attendance_session or record.get("AttendanceSession")
        )

        if session not in config.ATTENDANCE_SESSIONS:
            st.error("⚠️ حاضری کا درست وقت منتخب کریں۔")
            return False

        status = _clean(record.get("Status"))
        if status not in config.ATTENDANCE_STATUSES:
            st.error("⚠️ حاضری کی درست حالت منتخب کریں۔")
            return False

        prepared_records.append(
            {
                "AttendanceSession": session,
                "StudentName": _clean(record.get("StudentName")),
                "FatherName": _clean(record.get("FatherName")),
                "Status": status,
            }
        )

    existing_df = get_all_attendance()
    existing_keys: set[tuple[str, str, str]] = set()

    if not existing_df.empty:
        needed = {
            "Date",
            "AttendanceSession",
            "StudentName",
            "FatherName",
        }

        if needed.issubset(existing_df.columns):
            same_date = existing_df[
                existing_df["Date"].map(_date_key)
                == _date_key(date)
            ]

            for _, row in same_date.iterrows():
                existing_keys.add(
                    (
                        _normalise(row.get("AttendanceSession")),
                        _normalise(row.get("StudentName")),
                        _normalise(row.get("FatherName")),
                    )
                )

    incoming_keys: set[tuple[str, str, str]] = set()
    duplicate_names: list[str] = []

    for record in prepared_records:
        key = (
            _normalise(record["AttendanceSession"]),
            _normalise(record["StudentName"]),
            _normalise(record["FatherName"]),
        )

        if key in existing_keys or key in incoming_keys:
            duplicate_names.append(record["StudentName"])

        incoming_keys.add(key)

    if duplicate_names:
        st.error(
            "⚠️ درج ذیل طلباء کی منتخب وقت کی حاضری پہلے سے موجود ہے: "
            + "، ".join(_unique_non_empty(duplicate_names))
        )
        return False

    worksheet = _get_or_create_worksheet(
        config.SHEET_ATTENDANCE,
        config.ATTENDANCE_HEADERS,
    )
    time_now = now_time_str()

    rows = [
        _row_for_actual_headers(
            worksheet,
            {
                "Date": _clean(date),
                "AttendanceSession": record["AttendanceSession"],
                "StudentName": record["StudentName"],
                "FatherName": record["FatherName"],
                "TeacherUsername": _clean(teacher_username),
                "TeacherName": _clean(teacher_name),
                "Status": record["Status"],
                "TimeSubmitted": time_now,
            },
            config.ATTENDANCE_HEADERS,
        )
        for record in prepared_records
    ]

    saved = _append_rows(
        worksheet,
        rows,
        "حاضری محفوظ کرنے",
    )

    if not saved:
        return False

    # Google Sheets کو نئی rows دستیاب کرنے کے لیے مختصر مہلت دیں،
    # پھر تازہ direct read کے ذریعے تصدیق کریں۔
    time.sleep(0.5)

    try:
        fresh_records = _call_with_retry(
            lambda: worksheet.get_all_records(),
            "محفوظ شدہ حاضری کی تصدیق کرنے",
        )
    except Exception as error:
        st.error(
            "⚠️ حاضری بھیج دی گئی، لیکن اس کی تصدیق نہیں ہو سکی۔"
            f"\n\nتفصیل: {error}"
        )
        return False

    submitted_keys = {
        (
            _date_key(date),
            _normalise(record["AttendanceSession"]),
            _normalise(record["StudentName"]),
            _normalise(record["FatherName"]),
        )
        for record in prepared_records
    }

    saved_keys = {
        (
            _date_key(record.get("Date")),
            _normalise(record.get("AttendanceSession")),
            _normalise(record.get("StudentName")),
            _normalise(record.get("FatherName")),
        )
        for record in fresh_records
    }

    missing_keys = submitted_keys - saved_keys
    if missing_keys:
        st.error(
            "⚠️ حاضری Google Sheet میں صحیح کالموں کے تحت نہیں ملی۔ "
            "اب row اصل worksheet header ترتیب کے مطابق لکھی جا رہی ہے۔ "
            "براہِ کرم دوبارہ حاضری درج کریں۔"
        )
        return False

    clear_data_cache()
    return True


def _find_attendance_row(
    date: str,
    attendance_session: str,
    student_name: str,
    father_name: str,
    teacher_username: str | None = None,
):
    """
    Date + AttendanceSession + StudentName + FatherName سے row تلاش کریں۔

    teacher_username دینے پر استاد بھی موازنہ میں شامل ہوتا ہے۔
    """
    worksheet = _get_or_create_worksheet(
        config.SHEET_ATTENDANCE,
        config.ATTENDANCE_HEADERS,
    )

    try:
        records = _call_with_retry(
            lambda: worksheet.get_all_records(),
            "ورک شیٹ کا ڈیٹا پڑھنے",
        )
    except Exception as error:
        st.error(
            "⚠️ حاضری کا ریکارڈ تلاش کرنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return worksheet, None

    for index, record in enumerate(records):
        matches = (
            _date_key(record.get("Date")) == _date_key(date)
            and _normalise(record.get("AttendanceSession"))
            == _normalise(attendance_session)
            and _normalise(record.get("StudentName"))
            == _normalise(student_name)
            and _normalise(record.get("FatherName"))
            == _normalise(father_name)
        )

        if teacher_username is not None:
            matches = matches and (
                _normalise(record.get("TeacherUsername"))
                == _normalise(teacher_username)
            )

        if matches:
            return worksheet, index + 2

    return worksheet, None


def update_attendance_record(
    date: str,
    student_name: str,
    father_name: str,
    teacher_username: str,
    new_status: str,
    attendance_session: str | None = None,
) -> bool:
    """
    حاضری کی حالت تبدیل کریں۔

    نئی اسکرین کو attendance_session ضرور دینا چاہیے۔
    """
    if attendance_session is None:
        st.error("⚠️ حاضری کا وقت منتخب کرنا ضروری ہے۔")
        return False

    if new_status not in config.ATTENDANCE_STATUSES:
        st.error("⚠️ حاضری کی درست حالت منتخب کریں۔")
        return False

    worksheet, row_number = _find_attendance_row(
        date,
        attendance_session,
        student_name,
        father_name,
        teacher_username,
    )

    if row_number is None:
        st.error("⚠️ حاضری کا ریکارڈ نہیں ملا۔")
        return False

    return _update_cell(
        worksheet,
        row_number,
        config.ATTENDANCE_HEADERS.index("Status") + 1,
        _clean(new_status),
        "حاضری تبدیل کرنے",
    )


def delete_attendance_record(
    date: str,
    student_name: str,
    father_name: str,
    teacher_username: str,
    attendance_session: str | None = None,
) -> bool:
    """منتخب سیشن کا حاضری ریکارڈ حذف کریں۔"""
    if attendance_session is None:
        st.error("⚠️ حاضری کا وقت منتخب کرنا ضروری ہے۔")
        return False

    worksheet, row_number = _find_attendance_row(
        date,
        attendance_session,
        student_name,
        father_name,
        teacher_username,
    )

    if row_number is None:
        st.error("⚠️ حاضری کا ریکارڈ نہیں ملا۔")
        return False

    return _delete_row(worksheet, row_number, "حاضری کا ریکارڈ حذف کرنے")


# ==================================================
# Daily Educational Work
# ==================================================
def get_all_daily_work() -> pd.DataFrame:
    """تمام روزانہ تعلیمی ریکارڈ حاصل کریں۔"""
    return read_all_records(
        config.SHEET_DAILY_WORK,
        config.DAILY_WORK_HEADERS,
    )


def get_daily_work_for_date(date: str) -> pd.DataFrame:
    """منتخب تاریخ کا تمام تعلیمی کام حاصل کریں۔"""
    df = get_all_daily_work()

    if df.empty or "Date" not in df.columns:
        return df

    return df[
        df["Date"].map(_date_key)
        == _date_key(date)
    ].copy()


def daily_work_exists(
    date: str,
    student_name: str,
    father_name: str,
) -> bool:
    """طالب علم کا منتخب تاریخ میں تعلیمی ریکارڈ موجود ہونے کی جانچ کریں۔"""
    df = get_all_daily_work()

    if df.empty:
        return False

    required = {"Date", "StudentName", "FatherName"}
    if not required.issubset(df.columns):
        return False

    match = (
        df["Date"].map(_date_key) == _date_key(date)
    ) & (
        df["StudentName"].astype(str).map(_normalise)
        == _normalise(student_name)
    ) & (
        df["FatherName"].astype(str).map(_normalise)
        == _normalise(father_name)
    )

    return bool(match.any())


def _validate_daily_work_record(record: dict) -> bool:
    """تعلیمی ریکارڈ کی بنیادی جانچ کریں۔"""
    manzil_juz = _clean(record.get("ManzilJuz"))
    pao_juz = _clean(record.get("PaoJuz"))
    pao_quarter = _clean(record.get("PaoQuarter"))
    manzil_amount = _clean(record.get("ManzilAmount"))
    manzil_half = _clean(record.get("ManzilHalf"))

    if manzil_juz:
        try:
            if int(manzil_juz) not in config.JUZ_NUMBERS:
                raise ValueError
        except (TypeError, ValueError):
            st.error("⚠️ منزل کے لیے پارہ نمبر 1 سے 30 کے درمیان ہونا چاہیے۔")
            return False

        if manzil_amount not in config.MANZIL_AMOUNTS:
            st.error("⚠️ منزل کے لیے مکمل یا نصف منتخب کریں۔")
            return False

        if (
            manzil_amount == config.MANZIL_AMOUNT_HALF
            and manzil_half not in config.MANZIL_HALVES
        ):
            st.error("⚠️ نصف منزل کے لیے نصف اول یا نصف دوم منتخب کریں۔")
            return False

    if pao_juz:
        try:
            if int(pao_juz) not in config.JUZ_NUMBERS:
                raise ValueError
        except (TypeError, ValueError):
            st.error("⚠️ پاؤ کے لیے پارہ نمبر 1 سے 30 کے درمیان ہونا چاہیے۔")
            return False

        try:
            if int(pao_quarter) not in config.PAO_QUARTERS:
                raise ValueError
        except (TypeError, ValueError):
            st.error("⚠️ پاؤ نمبر 1 سے 4 کے درمیان ہونا چاہیے۔")
            return False

    return True


def submit_daily_work(
    date: str,
    teacher_username: str,
    teacher_name: str,
    records: list[dict],
) -> bool:
    """
    کئی طلباء کا روزانہ تعلیمی کام ایک ساتھ محفوظ کریں۔

    ہر record کی keys:
        StudentName, FatherName,
        SabaqSurah, SabaqAyah,
        SabqiSurah, SabqiAyah,
        ManzilJuz, ManzilAmount, ManzilHalf,
        PaoJuz, PaoQuarter
    """
    from utils import now_time_str

    if not records:
        return True

    existing_df = get_all_daily_work()
    existing_keys: set[tuple[str, str]] = set()

    if not existing_df.empty:
        needed = {"Date", "StudentName", "FatherName"}

        if needed.issubset(existing_df.columns):
            same_date = existing_df[
                existing_df["Date"].map(_date_key)
                == _date_key(date)
            ]

            for _, row in same_date.iterrows():
                existing_keys.add(
                    (
                        _normalise(row.get("StudentName")),
                        _normalise(row.get("FatherName")),
                    )
                )

    incoming_keys: set[tuple[str, str]] = set()
    duplicate_names: list[str] = []
    prepared: list[dict] = []

    for record in records:
        if not _validate_daily_work_record(record):
            return False

        key = (
            _normalise(record.get("StudentName")),
            _normalise(record.get("FatherName")),
        )

        if key in existing_keys or key in incoming_keys:
            duplicate_names.append(_clean(record.get("StudentName")))

        incoming_keys.add(key)
        prepared.append(record)

    if duplicate_names:
        st.error(
            "⚠️ درج ذیل طلباء کا آج کا تعلیمی کام پہلے سے موجود ہے: "
            + "، ".join(_unique_non_empty(duplicate_names))
        )
        return False

    worksheet = _get_or_create_worksheet(
        config.SHEET_DAILY_WORK,
        config.DAILY_WORK_HEADERS,
    )
    time_now = now_time_str()

    rows: list[list] = []

    for record in prepared:
        manzil_amount = _clean(record.get("ManzilAmount"))
        manzil_half = _clean(record.get("ManzilHalf"))

        if manzil_amount != config.MANZIL_AMOUNT_HALF:
            manzil_half = ""

        rows.append(
            [
                _clean(date),
                _clean(record.get("StudentName")),
                _clean(record.get("FatherName")),
                _clean(teacher_username),
                _clean(teacher_name),
                _clean(record.get("SabaqSurah")),
                _clean(record.get("SabaqAyah")),
                _clean(record.get("SabqiSurah")),
                _clean(record.get("SabqiAyah")),
                _clean(record.get("ManzilJuz")),
                manzil_amount,
                manzil_half,
                _clean(record.get("PaoJuz")),
                _clean(record.get("PaoQuarter")),
                time_now,
            ]
        )

    return _append_rows(worksheet, rows, "روزانہ تعلیمی کام محفوظ کرنے")


def _find_daily_work_row(
    date: str,
    student_name: str,
    father_name: str,
    teacher_username: str | None = None,
):
    """تعلیمی ریکارڈ کی Worksheet row تلاش کریں۔"""
    worksheet = _get_or_create_worksheet(
        config.SHEET_DAILY_WORK,
        config.DAILY_WORK_HEADERS,
    )

    try:
        records = _call_with_retry(
            lambda: worksheet.get_all_records(),
            "ورک شیٹ کا ڈیٹا پڑھنے",
        )
    except Exception as error:
        st.error(
            "⚠️ تعلیمی ریکارڈ تلاش کرنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return worksheet, None

    for index, record in enumerate(records):
        matches = (
            _date_key(record.get("Date")) == _date_key(date)
            and _normalise(record.get("StudentName"))
            == _normalise(student_name)
            and _normalise(record.get("FatherName"))
            == _normalise(father_name)
        )

        if teacher_username is not None:
            matches = matches and (
                _normalise(record.get("TeacherUsername"))
                == _normalise(teacher_username)
            )

        if matches:
            return worksheet, index + 2

    return worksheet, None


def update_daily_work_record(
    date: str,
    student_name: str,
    father_name: str,
    teacher_username: str,
    teacher_name: str,
    sabaq_surah: str = "",
    sabaq_ayah: str = "",
    sabqi_surah: str = "",
    sabqi_ayah: str = "",
    manzil_juz: str | int = "",
    manzil_amount: str = "",
    manzil_half: str = "",
    pao_juz: str | int = "",
    pao_quarter: str | int = "",
) -> bool:
    """طالب علم کا موجودہ روزانہ تعلیمی ریکارڈ مکمل طور پر تبدیل کریں۔"""
    from utils import now_time_str

    record = {
        "ManzilJuz": manzil_juz,
        "ManzilAmount": manzil_amount,
        "ManzilHalf": manzil_half,
        "PaoJuz": pao_juz,
        "PaoQuarter": pao_quarter,
    }

    if not _validate_daily_work_record(record):
        return False

    worksheet, row_number = _find_daily_work_row(
        date,
        student_name,
        father_name,
        teacher_username,
    )

    if row_number is None:
        st.error("⚠️ روزانہ تعلیمی ریکارڈ نہیں ملا۔")
        return False

    if manzil_amount != config.MANZIL_AMOUNT_HALF:
        manzil_half = ""

    values = [
        _clean(date),
        _clean(student_name),
        _clean(father_name),
        _clean(teacher_username),
        _clean(teacher_name),
        _clean(sabaq_surah),
        _clean(sabaq_ayah),
        _clean(sabqi_surah),
        _clean(sabqi_ayah),
        _clean(manzil_juz),
        _clean(manzil_amount),
        _clean(manzil_half),
        _clean(pao_juz),
        _clean(pao_quarter),
        now_time_str(),
    ]

    return _update_row_range(
        worksheet,
        row_number,
        values,
        "روزانہ تعلیمی کام تبدیل کرنے",
    )


def delete_daily_work_record(
    date: str,
    student_name: str,
    father_name: str,
    teacher_username: str | None = None,
) -> bool:
    """روزانہ تعلیمی ریکارڈ حذف کریں۔"""
    worksheet, row_number = _find_daily_work_row(
        date,
        student_name,
        father_name,
        teacher_username,
    )

    if row_number is None:
        st.error("⚠️ روزانہ تعلیمی ریکارڈ نہیں ملا۔")
        return False

    return _delete_row(
        worksheet,
        row_number,
        "روزانہ تعلیمی ریکارڈ حذف کرنے",
    )


# ==================================================
# Activity Logs
# ==================================================
def get_all_logs() -> pd.DataFrame:
    return read_all_records(config.SHEET_LOGS, config.LOGS_HEADERS)


def add_log(username: str, action: str) -> bool:
    from utils import now_time_str, today_str

    worksheet = _get_or_create_worksheet(
        config.SHEET_LOGS,
        config.LOGS_HEADERS,
    )

    return _append_row(
        worksheet,
        [
            today_str(),
            now_time_str(),
            _clean(username),
            _clean(action),
        ],
        "سرگرمی کا اندراج کرنے",
    )


# ==================================================
# Settings
# ==================================================
def get_setting(key: str, default=None):
    df = read_all_records(
        config.SHEET_SETTINGS,
        config.SETTINGS_HEADERS,
    )

    if df.empty or "Key" not in df.columns:
        return default

    match = df[
        df["Key"].astype(str).map(_normalise)
        == _normalise(key)
    ]

    if match.empty:
        return default

    return match.iloc[0].get("Value", default)


def set_setting(key: str, value: str) -> bool:
    worksheet = _get_or_create_worksheet(
        config.SHEET_SETTINGS,
        config.SETTINGS_HEADERS,
    )

    try:
        records = _call_with_retry(
            lambda: worksheet.get_all_records(),
            "ورک شیٹ کا ڈیٹا پڑھنے",
        )
    except Exception as error:
        st.error(
            "⚠️ ترتیبات تلاش کرنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return False

    target_key = _normalise(key)

    for index, record in enumerate(records):
        if _normalise(record.get("Key")) == target_key:
            return _update_cell(
                worksheet,
                index + 2,
                2,
                _clean(value),
                "ترتیب تبدیل کرنے",
            )

    return _append_row(
        worksheet,
        [_clean(key), _clean(value)],
        "نئی ترتیب شامل کرنے",
    )