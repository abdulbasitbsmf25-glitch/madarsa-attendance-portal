# sheets.py
"""
گوگل شیٹس (Database) کے ساتھ رابطہ کرنے والی فائل
==================================================
یہ فائل gspread استعمال کرتے ہوئے Google Sheets کو بطور ڈیٹا بیس استعمال کرتی ہے۔

اہم ذمہ داریاں:
    1) Google Sheets کے ساتھ محفوظ کنکشن قائم کرنا
    2) ضروری Worksheets خودکار طور پر بنانا
    3) Users, Students, Attendance, DailyWork, Logs اور Settings کا ڈیٹا سنبھالنا
    4) تمام Database operations کو ایک ہی فائل میں رکھنا

نیا Student/Attendance نظام:
    - RollNumber استعمال نہیں ہوتا۔
    - طالب علم کے لیے StudentName + FatherName + AssignedTeacher استعمال ہوتا ہے۔
    - Attendance میں StudentName + FatherName + Date کے ذریعے duplicate روکا جاتا ہے۔
    - Attendance record میں صبح/دوپہر کا سیشن بھی محفوظ ہوتا ہے۔
    - DailyWork میں سبق، سبقی، منزل، پاؤ اور کیفیت محفوظ ہوتی ہے۔
"""

from __future__ import annotations

import string
import time
from threading import RLock
from pathlib import Path
from typing import Any

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


# ==================================================
# عمومی مددگار فنکشنز
# ==================================================
def _clean(value: Any) -> str:
    """کسی بھی value کو محفوظ، صاف string میں تبدیل کریں۔"""
    if value is None:
        return ""
    return str(value).strip()


def _normalise(value: Any) -> str:
    """Comparison کے لیے value کو lowercase اور trimmed بنائیں۔"""
    return _clean(value).casefold()


def _column_letter(column_number: int) -> str:
    """
    1-based column number کو Google Sheets column letter میں تبدیل کریں۔
    مثال: 1 -> A، 26 -> Z، 27 -> AA
    """
    if column_number < 1:
        raise ValueError("Column number must be at least 1.")

    letters = ""
    number = column_number

    while number:
        number, remainder = divmod(number - 1, 26)
        letters = string.ascii_uppercase[remainder] + letters

    return letters


def _dataframe_with_headers(
    records: list[dict],
    headers: list[str],
) -> pd.DataFrame:
    """
    DataFrame بنائیں اور یقینی بنائیں کہ تمام متوقع columns موجود ہوں۔
    اضافی columns کو ضائع نہیں کیا جاتا۔
    """
    df = pd.DataFrame(records)

    if df.empty:
        return pd.DataFrame(columns=headers)

    for header in headers:
        if header not in df.columns:
            df[header] = ""

    ordered_columns = headers + [
        column
        for column in df.columns
        if column not in headers
    ]

    return df[ordered_columns]


@st.cache_resource(show_spinner=False)
def _runtime_state() -> dict:
    """
    تمام sessions کے درمیان مشترک ہلکی runtime state۔

    - worksheet objects دوبارہ حاصل نہیں کیے جاتے
    - headers بار بار نہیں پڑھے جاتے
    - ہر sheet کا الگ data-cache version رکھا جاتا ہے
    """
    return {
        "worksheets": {},
        "headers": {},
        "versions": {},
        "lock": RLock(),
    }


def _is_quota_error(error: Exception) -> bool:
    """Google API کے 429/quota error کو پہچانیں۔"""
    message = str(error).casefold()
    return (
        "429" in message
        or "quota exceeded" in message
        or "rate limit" in message
        or "resource_exhausted" in message
    )


def _call_with_backoff(
    operation,
    action_desc: str,
    attempts: int = 5,
):
    """
    429 error کی صورت میں Google کی سفارش کے مطابق exponential backoff۔

    درخواستیں فوراً بار بار بھیجنے کے بجائے 2، 4، 8 اور 16 سیکنڈ
    انتظار کے بعد دوبارہ کوشش کی جاتی ہے۔
    """
    last_error = None

    for attempt in range(attempts):
        try:
            return operation()

        except Exception as error:
            last_error = error

            if not _is_quota_error(error) or attempt == attempts - 1:
                raise

            time.sleep(2 ** (attempt + 1))

    raise last_error


def _get_cached_headers(
    worksheet,
    expected_headers: list[str],
) -> list[str]:
    """
    Worksheet headers صرف پہلی ضرورت پر پڑھیں اور memory میں محفوظ رکھیں۔

    Missing headers صرف ایک بار آخر میں شامل ہوتے ہیں، ہر Streamlit rerun
    پر نہیں۔
    """
    state = _runtime_state()
    sheet_name = worksheet.title

    with state["lock"]:
        cached = state["headers"].get(sheet_name)

    if cached:
        return list(cached)

    try:
        actual_headers = _call_with_backoff(
            lambda: [
                _clean(value)
                for value in worksheet.row_values(1)
            ],
            f"'{sheet_name}' کے headers پڑھنے",
        )

        if not actual_headers:
            actual_headers = list(expected_headers)
            _call_with_backoff(
                lambda: worksheet.append_row(
                    actual_headers,
                    value_input_option="RAW",
                ),
                f"'{sheet_name}' کے headers بنانے",
            )
        else:
            missing_headers = [
                header
                for header in expected_headers
                if header not in actual_headers
            ]

            if missing_headers:
                actual_headers = actual_headers + missing_headers
                last_column = _column_letter(len(actual_headers))

                _call_with_backoff(
                    lambda: worksheet.update(
                        values=[actual_headers],
                        range_name=f"A1:{last_column}1",
                    ),
                    f"'{sheet_name}' کے headers update کرنے",
                )

        with state["lock"]:
            state["headers"][sheet_name] = list(actual_headers)

        return list(actual_headers)

    except Exception as error:
        st.error(
            f"⚠️ '{sheet_name}' کے headers تیار نہیں ہو سکے۔"
            f"\n\nتفصیل: {error}"
        )
        return list(expected_headers)


def _row_for_actual_headers(
    actual_headers: list[str],
    record: dict[str, Any],
) -> list[str]:
    """حقیقی Worksheet header order کے مطابق row تیار کریں۔"""
    return [
        _clean(record.get(header, ""))
        for header in actual_headers
    ]


def _sheet_version(sheet_name: str) -> int:
    """منتخب sheet کا موجودہ cache version واپس کریں۔"""
    state = _runtime_state()

    with state["lock"]:
        return int(state["versions"].get(sheet_name, 0))


def _invalidate_sheet_cache(sheet_name: str) -> None:
    """
    صرف تبدیل ہونے والی sheet کا cache invalid کریں۔

    پوری application کا cache صاف نہیں کیا جاتا، اس لیے ایک write کے بعد
    Users, Logs, Settings اور دوسری sheets دوبارہ read نہیں ہوتیں۔
    """
    state = _runtime_state()

    with state["lock"]:
        state["versions"][sheet_name] = (
            int(state["versions"].get(sheet_name, 0)) + 1
        )


# ==================================================
# 1) Google Sheets Authentication
# ==================================================
@st.cache_resource(show_spinner=False)
def get_client():
    """
    Google Sheets کے لیے gspread client تیار کریں۔

    Streamlit Cloud پر st.secrets["gcp_service_account"] استعمال ہوتا ہے۔
    Local computer پر config.CREDENTIALS_FILE استعمال ہوتی ہے۔
    """
    try:
        credentials = None

        try:
            service_account_info = dict(
                st.secrets["gcp_service_account"]
            )

            credentials = (
                Credentials.from_service_account_info(
                    service_account_info,
                    scopes=SCOPES,
                )
            )
        except Exception:
            credentials_path = Path(
                config.CREDENTIALS_FILE
            )

            if not credentials_path.exists():
                st.error(
                    "⚠️ credentials.json فائل نہیں ملی۔\n\n"
                    f"متوقع جگہ: {credentials_path.resolve()}"
                )
                st.stop()

            credentials = (
                Credentials.from_service_account_file(
                    str(credentials_path),
                    scopes=SCOPES,
                )
            )

        return gspread.authorize(credentials)

    except Exception as error:
        st.error(
            "⚠️ Google Sheets کے ساتھ کنکشن قائم نہیں ہو سکا۔"
        )
        st.exception(error)
        st.stop()


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    """
    مرکزی Google Spreadsheet کھولیں۔
    موجود نہ ہونے پر نئی Spreadsheet بنانے کی کوشش کریں۔
    """
    client = get_client()

    try:
        return client.open(config.GOOGLE_SHEET_NAME)

    except gspread.SpreadsheetNotFound:
        try:
            return client.create(
                config.GOOGLE_SHEET_NAME
            )
        except Exception as error:
            st.error(
                "⚠️ نئی Google Spreadsheet نہیں بنائی جا سکی۔ "
                "Service Account کی Drive permissions چیک کریں."
                f"\n\nتفصیل: {error}"
            )
            st.stop()

    except Exception as error:
        st.error(
            "⚠️ Google Spreadsheet کھولنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        st.stop()


def clear_cache():
    """
    تمام cached connections اور data دستی طور پر صاف کریں۔

    اسے صرف backup/restore یا واقعی manual refresh کے وقت استعمال کریں۔
    عام add/update/delete operations صرف متعلقہ sheet کا cache invalid
    کرتی ہیں۔
    """
    get_client.clear()
    get_spreadsheet.clear()
    _read_all_records_cached.clear()
    _initialize_database_once.clear()
    _runtime_state.clear()


# ==================================================
# 2) Worksheets بنانا اور چیک کرنا
# ==================================================
def _get_or_create_worksheet(
    sheet_name: str,
    headers: list[str],
):
    """
    Worksheet object process-wide cache سے حاصل کریں۔

    اہم فرق:
    یہ function ہر call پر get_all_values() نہیں چلاتا۔ یہی پرانے code
    میں quota بڑھنے کی بڑی وجہ تھی۔
    """
    state = _runtime_state()

    with state["lock"]:
        cached = state["worksheets"].get(sheet_name)

    if cached is not None:
        return cached

    spreadsheet = get_spreadsheet()

    try:
        worksheet = _call_with_backoff(
            lambda: spreadsheet.worksheet(sheet_name),
            f"'{sheet_name}' Worksheet حاصل کرنے",
        )

    except gspread.WorksheetNotFound:
        try:
            worksheet = _call_with_backoff(
                lambda: spreadsheet.add_worksheet(
                    title=sheet_name,
                    rows=1000,
                    cols=max(len(headers), 5),
                ),
                f"'{sheet_name}' Worksheet بنانے",
            )

        except Exception as error:
            st.error(
                f"⚠️ '{sheet_name}' Worksheet نہیں بنائی جا سکی۔"
                f"\n\nتفصیل: {error}"
            )
            st.stop()

    except Exception as error:
        st.error(
            f"⚠️ '{sheet_name}' Worksheet تک رسائی نہیں ہو سکی۔"
            f"\n\nتفصیل: {error}"
        )
        st.stop()

    with state["lock"]:
        state["worksheets"][sheet_name] = worksheet

    return worksheet


@st.cache_resource(show_spinner=False)
def _initialize_database_once() -> bool:
    """
    Database structure پوری deployed process میں صرف ایک بار چیک کریں۔

    ہر user session اور ہر Streamlit rerun پر چھ worksheets دوبارہ read
    نہیں کی جاتیں۔
    """
    worksheet_specs = [
        (config.SHEET_USERS, config.USERS_HEADERS),
        (config.SHEET_STUDENTS, config.STUDENTS_HEADERS),
        (config.SHEET_ATTENDANCE, config.ATTENDANCE_HEADERS),
        (config.SHEET_DAILY_WORK, config.DAILY_WORK_HEADERS),
        (config.SHEET_LOGS, config.LOGS_HEADERS),
        (config.SHEET_SETTINGS, config.SETTINGS_HEADERS),
    ]

    worksheets = {}

    for sheet_name, headers in worksheet_specs:
        worksheet = _get_or_create_worksheet(
            sheet_name,
            headers,
        )
        _get_cached_headers(worksheet, headers)
        worksheets[sheet_name] = worksheet

    users_ws = worksheets[config.SHEET_USERS]

    try:
        users_records = _call_with_backoff(
            users_ws.get_all_records,
            "Users Worksheet پڑھنے",
        )

    except Exception as error:
        st.error(
            "⚠️ Users Worksheet پڑھنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        st.stop()

    if not users_records:
        rows = []

        for user in config.DEFAULT_USERS:
            rows.append(
                [
                    _clean(user.get("Username")),
                    hash_password(
                        _clean(user.get("Password"))
                    ),
                    _clean(user.get("FullName")),
                    _clean(user.get("Role")),
                    "TRUE",
                ]
            )

        try:
            _call_with_backoff(
                lambda: users_ws.append_rows(
                    rows,
                    value_input_option="RAW",
                ),
                "Default users شامل کرنے",
            )
            _invalidate_sheet_cache(config.SHEET_USERS)

        except Exception as error:
            st.error(
                "⚠️ Default users شامل نہیں ہو سکے۔"
                f"\n\nتفصیل: {error}"
            )
            st.stop()

    return True


def initialize_database():
    """Database initialization کو process-wide cached helper سے چلائیں۔"""
    _initialize_database_once()


# ==================================================
# 3) عمومی CRUD فنکشنز
# ==================================================
@st.cache_data(
    ttl=600,
    max_entries=128,
    show_spinner=False,
)
def _read_all_records_cached(
    sheet_name: str,
    headers_tuple: tuple[str, ...],
    version: int,
) -> pd.DataFrame:
    """
    ایک sheet کو زیادہ سے زیادہ ہر 10 منٹ بعد دوبارہ read کریں۔

    Write کے فوراً بعد صرف اسی sheet کا version بدلتا ہے، جس سے fresh data
    مل جاتا ہے اور باقی worksheets cache میں رہتی ہیں۔
    """
    del version  # cache key کے لیے استعمال ہوتا ہے

    headers = list(headers_tuple)
    worksheet = _get_or_create_worksheet(
        sheet_name,
        headers,
    )

    try:
        records = _call_with_backoff(
            worksheet.get_all_records,
            f"'{sheet_name}' سے data پڑھنے",
        )

    except Exception as error:
        if _is_quota_error(error):
            st.error(
                "⚠️ Google Sheets کی request limit عارضی طور پر پوری ہے۔ "
                "Application نے خودکار طور پر کئی بار انتظار کے ساتھ کوشش "
                "کی، مگر Google نے ابھی اجازت نہیں دی۔ کچھ دیر بعد دوبارہ "
                "کوشش کریں۔"
            )
        else:
            st.error(
                f"⚠️ '{sheet_name}' سے data پڑھنے میں خرابی پیش آئی۔"
                f"\n\nتفصیل: {error}"
            )

        return pd.DataFrame(columns=headers)

    return _dataframe_with_headers(records, headers)


def read_all_records(
    sheet_name: str,
    headers: list[str],
) -> pd.DataFrame:
    """Worksheet data کو sheet-specific versioned cache سے پڑھیں۔"""
    return _read_all_records_cached(
        sheet_name,
        tuple(headers),
        _sheet_version(sheet_name),
    ).copy()

def _append_row(
    worksheet,
    row: list,
    action_desc: str = "Data شامل کرنے",
) -> bool:
    """Worksheet میں ایک نئی row شامل کریں۔"""
    try:
        _call_with_backoff(
            lambda: worksheet.append_row(
                row,
                value_input_option="RAW",
            ),
            action_desc,
        )
        _invalidate_sheet_cache(worksheet.title)
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
    action_desc: str = "Data شامل کرنے",
) -> bool:
    """Worksheet میں کئی rows ایک batch request میں شامل کریں۔"""
    try:
        if rows:
            _call_with_backoff(
                lambda: worksheet.append_rows(
                    rows,
                    value_input_option="RAW",
                ),
                action_desc,
            )
            _invalidate_sheet_cache(worksheet.title)

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
    action_desc: str = "Data update کرنے",
) -> bool:
    """Worksheet کے ایک cell کو update کریں۔"""
    try:
        _call_with_backoff(
            lambda: worksheet.update_cell(
                row,
                column,
                value,
            ),
            action_desc,
        )
        _invalidate_sheet_cache(worksheet.title)
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
    action_desc: str = "Data update کرنے",
) -> bool:
    """Worksheet کی مکمل row کو ایک batch request میں update کریں۔"""
    try:
        last_column = _column_letter(len(values))

        _call_with_backoff(
            lambda: worksheet.update(
                values=[values],
                range_name=f"A{row}:{last_column}{row}",
            ),
            action_desc,
        )
        _invalidate_sheet_cache(worksheet.title)
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
    action_desc: str = "Data حذف کرنے",
) -> bool:
    """Worksheet سے ایک row حذف کریں۔"""
    try:
        _call_with_backoff(
            lambda: worksheet.delete_rows(row),
            action_desc,
        )
        _invalidate_sheet_cache(worksheet.title)
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
    """Backward-compatible alias۔"""
    return read_all_records(
        sheet_name,
        headers,
    )


# ==================================================
# Users
# ==================================================
def get_all_users() -> pd.DataFrame:
    return read_all_records(
        config.SHEET_USERS,
        config.USERS_HEADERS,
    )


def get_user(username: str):
    df = get_all_users()

    if df.empty or "Username" not in df.columns:
        return None

    username_normalised = _normalise(username)

    match = df[
        df["Username"]
        .astype(str)
        .map(_normalise)
        == username_normalised
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
    """Cached Users DataFrame سے row number تلاش کریں۔"""
    worksheet = _get_or_create_worksheet(
        config.SHEET_USERS,
        config.USERS_HEADERS,
    )
    df = get_all_users()
    target = _normalise(username)

    if df.empty or "Username" not in df.columns:
        return worksheet, None

    for dataframe_index, record in df.reset_index(drop=True).iterrows():
        if _normalise(record.get("Username")) == target:
            return worksheet, dataframe_index + 2

    return worksheet, None

def update_user_password(
    username: str,
    new_password: str,
) -> bool:
    worksheet, row_number = _find_user_row(
        username
    )

    if row_number is None:
        st.error("⚠️ صارف نہیں ملا۔")
        return False

    return _update_cell(
        worksheet,
        row_number,
        2,
        hash_password(new_password),
        "Password تبدیل کرنے",
    )


def update_user_info(
    username: str,
    fullname: str | None = None,
    active: bool | None = None,
) -> bool:
    worksheet, row_number = _find_user_row(
        username
    )

    if row_number is None:
        st.error("⚠️ صارف نہیں ملا۔")
        return False

    success = True

    if fullname is not None:
        success = (
            _update_cell(
                worksheet,
                row_number,
                3,
                _clean(fullname),
                "صارف کی معلومات update کرنے",
            )
            and success
        )

    if active is not None:
        success = (
            _update_cell(
                worksheet,
                row_number,
                5,
                "TRUE" if active else "FALSE",
                "صارف کی حیثیت تبدیل کرنے",
            )
            and success
        )

    return success


def delete_user(username: str) -> bool:
    worksheet, row_number = _find_user_row(
        username
    )

    if row_number is None:
        st.error("⚠️ صارف نہیں ملا۔")
        return False

    return _delete_row(
        worksheet,
        row_number,
        "صارف حذف کرنے",
    )


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
        df["Status"]
        .astype(str)
        .str.strip()
        == config.STUDENT_STATUS_ACTIVE
    ].copy()


def student_exists(
    student_name: str,
    father_name: str,
    assigned_teacher: str | None = None,
) -> bool:
    """
    StudentName + FatherName کے ذریعے duplicate check کریں۔
    assigned_teacher دینے پر وہ بھی comparison میں شامل ہوتا ہے۔
    """
    df = get_all_students()

    if df.empty:
        return False

    required_columns = {
        "StudentName",
        "FatherName",
    }

    if not required_columns.issubset(df.columns):
        return False

    match = (
        df["StudentName"]
        .astype(str)
        .map(_normalise)
        == _normalise(student_name)
    ) & (
        df["FatherName"]
        .astype(str)
        .map(_normalise)
        == _normalise(father_name)
    )

    if (
        assigned_teacher is not None
        and "AssignedTeacher" in df.columns
    ):
        match = match & (
            df["AssignedTeacher"]
            .astype(str)
            .map(_normalise)
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

    if student_exists(
        name,
        father_name,
        assigned_teacher,
    ):
        st.error(
            "⚠️ یہی طالب علم اسی استاد کے ساتھ پہلے سے موجود ہے۔"
        )
        return False

    row = [
        _clean(name),
        _clean(father_name),
        _clean(assigned_teacher),
        _clean(age),
        _clean(phone),
        _clean(address),
        _clean(admission_date),
        config.STUDENT_STATUS_ACTIVE,
    ]

    return _append_row(
        worksheet,
        row,
        "نیا طالب علم شامل کرنے",
    )


def _find_student_row(
    student_name: str,
    father_name: str,
    assigned_teacher: str,
):
    """Cached Students DataFrame سے exact row number تلاش کریں۔"""
    worksheet = _get_or_create_worksheet(
        config.SHEET_STUDENTS,
        config.STUDENTS_HEADERS,
    )
    df = get_all_students()

    target_name = _normalise(student_name)
    target_father = _normalise(father_name)
    target_teacher = _normalise(assigned_teacher)

    for dataframe_index, record in df.reset_index(drop=True).iterrows():
        if (
            _normalise(record.get("StudentName")) == target_name
            and _normalise(record.get("FatherName")) == target_father
            and _normalise(record.get("AssignedTeacher")) == target_teacher
        ):
            return worksheet, dataframe_index + 2

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
        _normalise(original_name)
        != _normalise(name)
        or _normalise(original_father_name)
        != _normalise(father_name)
        or _normalise(original_assigned_teacher)
        != _normalise(assigned_teacher)
    )

    if identity_changed and student_exists(
        name,
        father_name,
        assigned_teacher,
    ):
        st.error(
            "⚠️ نئی معلومات کے ساتھ یہی طالب علم پہلے سے موجود ہے۔"
        )
        return False

    values = [
        _clean(name),
        _clean(father_name),
        _clean(assigned_teacher),
        _clean(age),
        _clean(phone),
        _clean(address),
        _clean(admission_date),
        _clean(status),
    ]

    return _update_row_range(
        worksheet,
        row_number,
        values,
        "طالب علم کی معلومات update کرنے",
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

    status_column = (
        config.STUDENTS_HEADERS.index(
            "Status"
        )
        + 1
    )

    return _update_cell(
        worksheet,
        row_number,
        status_column,
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

    return _delete_row(
        worksheet,
        row_number,
        "طالب علم حذف کرنے",
    )


# ==================================================
# Attendance
# ==================================================
def get_all_attendance() -> pd.DataFrame:
    return read_all_records(
        config.SHEET_ATTENDANCE,
        config.ATTENDANCE_HEADERS,
    )


def attendance_exists_for_student(
    date: str,
    student_name: str,
    father_name: str,
    attendance_session: str | None = None,
) -> bool:
    """
    ایک تاریخ اور سیشن میں طالب علم کی attendance پہلے سے موجود ہے یا نہیں۔

    attendance_session نہ دینے پر backward-compatible طور پر پوری تاریخ
    میں کسی بھی attendance record کو تلاش کیا جاتا ہے۔
    """
    df = get_all_attendance()

    if df.empty:
        return False

    required_columns = {"Date", "StudentName", "FatherName"}
    if not required_columns.issubset(df.columns):
        return False

    match = (
        df["Date"].astype(str).map(_normalise)
        == _normalise(date)
    ) & (
        df["StudentName"].astype(str).map(_normalise)
        == _normalise(student_name)
    ) & (
        df["FatherName"].astype(str).map(_normalise)
        == _normalise(father_name)
    )

    if (
        attendance_session is not None
        and "AttendanceSession" in df.columns
    ):
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
    """منتخب تاریخ، استاد اور اختیاری سیشن کا record تلاش کریں۔"""
    df = get_all_attendance()

    if df.empty or not {"Date", "TeacherName"}.issubset(df.columns):
        return False

    match = (
        df["Date"].astype(str).map(_normalise)
        == _normalise(date)
    ) & (
        df["TeacherName"].astype(str).map(_normalise)
        == _normalise(teacher_name)
    )

    if (
        attendance_session is not None
        and "AttendanceSession" in df.columns
    ):
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
    attendance_session: str = "",
) -> bool:
    """
    کئی طلباء کی ایک attendance session ایک ساتھ شامل کریں۔

    Duplicate rule:
        Date + AttendanceSession + StudentName + FatherName
    """
    from utils import now_time_str

    if not records:
        return True

    existing_df = get_all_attendance()
    existing_keys: set[tuple[str, str]] = set()

    if not existing_df.empty:
        required = {"Date", "StudentName", "FatherName"}

        if required.issubset(existing_df.columns):
            same_date = (
                existing_df["Date"].astype(str).map(_normalise)
                == _normalise(date)
            )

            if (
                attendance_session
                and "AttendanceSession" in existing_df.columns
            ):
                same_date = same_date & (
                    existing_df["AttendanceSession"]
                    .astype(str)
                    .map(_normalise)
                    == _normalise(attendance_session)
                )

            same_session_df = existing_df[same_date]

            for _, existing_record in same_session_df.iterrows():
                existing_keys.add(
                    (
                        _normalise(existing_record.get("StudentName")),
                        _normalise(existing_record.get("FatherName")),
                    )
                )

    incoming_keys: set[tuple[str, str]] = set()
    duplicate_names: list[str] = []

    for record in records:
        key = (
            _normalise(record.get("StudentName")),
            _normalise(record.get("FatherName")),
        )

        if key in existing_keys or key in incoming_keys:
            duplicate_names.append(_clean(record.get("StudentName")))

        incoming_keys.add(key)

    if duplicate_names:
        st.error(
            "⚠️ درج ذیل طلباء کی یہ حاضری پہلے سے موجود ہے: "
            + ", ".join(name for name in duplicate_names if name)
        )
        return False

    worksheet = _get_or_create_worksheet(
        config.SHEET_ATTENDANCE,
        config.ATTENDANCE_HEADERS,
    )
    actual_headers = _get_cached_headers(
        worksheet,
        config.ATTENDANCE_HEADERS,
    )
    time_now = now_time_str()

    rows = []
    for record in records:
        row_record = {
            "Date": date,
            "AttendanceSession": attendance_session,
            "StudentName": record.get("StudentName"),
            "FatherName": record.get("FatherName"),
            "TeacherUsername": teacher_username,
            "TeacherName": teacher_name,
            "Status": record.get("Status"),
            "TimeSubmitted": time_now,
        }
        rows.append(
            _row_for_actual_headers(actual_headers, row_record)
        )

    return _append_rows(
        worksheet,
        rows,
        "حاضری جمع کروانے",
    )


def _find_attendance_row(
    date: str,
    student_name: str,
    father_name: str,
    teacher_username: str,
    attendance_session: str | None = None,
):
    """Cached Attendance DataFrame سے record row تلاش کریں۔"""
    worksheet = _get_or_create_worksheet(
        config.SHEET_ATTENDANCE,
        config.ATTENDANCE_HEADERS,
    )
    df = get_all_attendance()

    for dataframe_index, record in df.reset_index(drop=True).iterrows():
        matched = (
            _normalise(record.get("Date")) == _normalise(date)
            and _normalise(record.get("StudentName"))
            == _normalise(student_name)
            and _normalise(record.get("FatherName"))
            == _normalise(father_name)
            and _normalise(record.get("TeacherUsername"))
            == _normalise(teacher_username)
        )

        if matched and attendance_session is not None:
            matched = (
                _normalise(record.get("AttendanceSession"))
                == _normalise(attendance_session)
            )

        if matched:
            return worksheet, dataframe_index + 2

    return worksheet, None

def update_attendance_record(
    date: str,
    student_name: str,
    father_name: str,
    teacher_username: str,
    new_status: str,
    attendance_session: str | None = None,
) -> bool:
    worksheet, row_number = _find_attendance_row(
        date,
        student_name,
        father_name,
        teacher_username,
        attendance_session,
    )

    if row_number is None:
        st.error("⚠️ حاضری کا record نہیں ملا۔")
        return False

    actual_headers = _get_cached_headers(
        worksheet,
        config.ATTENDANCE_HEADERS,
    )

    if "Status" not in actual_headers:
        st.error("⚠️ Attendance sheet میں Status کالم موجود نہیں۔")
        return False

    return _update_cell(
        worksheet,
        row_number,
        actual_headers.index("Status") + 1,
        _clean(new_status),
        "حاضری update کرنے",
    )


def delete_attendance_record(
    date: str,
    student_name: str,
    father_name: str,
    teacher_username: str,
    attendance_session: str | None = None,
) -> bool:
    worksheet, row_number = _find_attendance_row(
        date,
        student_name,
        father_name,
        teacher_username,
        attendance_session,
    )

    if row_number is None:
        st.error("⚠️ حاضری کا record نہیں ملا۔")
        return False

    return _delete_row(
        worksheet,
        row_number,
        "حاضری کا record حذف کرنے",
    )


# ==================================================
# Daily Educational Work
# ==================================================
def get_all_daily_work() -> pd.DataFrame:
    """تمام روزانہ تعلیمی کام records واپس کریں۔"""
    return read_all_records(
        config.SHEET_DAILY_WORK,
        config.DAILY_WORK_HEADERS,
    )


def daily_work_exists_for_student(
    date: str,
    student_name: str,
    father_name: str,
) -> bool:
    """ایک طالب علم کا ایک تاریخ میں تعلیمی record پہلے سے موجود ہے یا نہیں۔"""
    df = get_all_daily_work()

    if df.empty:
        return False

    required = {"Date", "StudentName", "FatherName"}
    if not required.issubset(df.columns):
        return False

    match = (
        df["Date"].astype(str).map(_normalise)
        == _normalise(date)
    ) & (
        df["StudentName"].astype(str).map(_normalise)
        == _normalise(student_name)
    ) & (
        df["FatherName"].astype(str).map(_normalise)
        == _normalise(father_name)
    )

    return bool(match.any())


def submit_daily_work(
    date: str,
    teacher_username: str,
    teacher_name: str,
    records: list[dict],
) -> bool:
    """
    روزانہ تعلیمی کام محفوظ کریں۔

    ہر record میں سبق، سبقی، منزل، پاؤ اور Remarks/کیفیت شامل ہو سکتی ہے۔
    """
    from utils import now_time_str

    if not records:
        return True

    existing_df = get_all_daily_work()
    existing_keys: set[tuple[str, str]] = set()

    if not existing_df.empty:
        required = {"Date", "StudentName", "FatherName"}
        if required.issubset(existing_df.columns):
            same_date_df = existing_df[
                existing_df["Date"].astype(str).map(_normalise)
                == _normalise(date)
            ]

            for _, existing_record in same_date_df.iterrows():
                existing_keys.add(
                    (
                        _normalise(existing_record.get("StudentName")),
                        _normalise(existing_record.get("FatherName")),
                    )
                )

    incoming_keys: set[tuple[str, str]] = set()
    duplicate_names: list[str] = []

    for record in records:
        key = (
            _normalise(record.get("StudentName")),
            _normalise(record.get("FatherName")),
        )

        if key in existing_keys or key in incoming_keys:
            duplicate_names.append(_clean(record.get("StudentName")))

        incoming_keys.add(key)

    if duplicate_names:
        st.error(
            "⚠️ درج ذیل طلباء کا تعلیمی کام اس تاریخ میں پہلے سے موجود ہے: "
            + ", ".join(name for name in duplicate_names if name)
        )
        return False

    worksheet = _get_or_create_worksheet(
        config.SHEET_DAILY_WORK,
        config.DAILY_WORK_HEADERS,
    )
    actual_headers = _get_cached_headers(
        worksheet,
        config.DAILY_WORK_HEADERS,
    )
    time_now = now_time_str()

    rows = []
    for record in records:
        row_record = {
            "Date": date,
            "StudentName": record.get("StudentName"),
            "FatherName": record.get("FatherName"),
            "TeacherUsername": teacher_username,
            "TeacherName": teacher_name,
            "SabaqSurah": record.get("SabaqSurah"),
            "SabaqAyah": record.get("SabaqAyah"),
            "SabqiSurah": record.get("SabqiSurah"),
            "SabqiAyah": record.get("SabqiAyah"),
            "ManzilJuz": record.get("ManzilJuz"),
            "ManzilAmount": record.get("ManzilAmount"),
            "ManzilHalf": record.get("ManzilHalf"),
            "PaoJuz": record.get("PaoJuz"),
            "PaoQuarter": record.get("PaoQuarter"),
            "Remarks": record.get("Remarks"),
            "TimeSubmitted": time_now,
        }
        rows.append(
            _row_for_actual_headers(actual_headers, row_record)
        )

    return _append_rows(
        worksheet,
        rows,
        "تعلیمی کام محفوظ کرنے",
    )


def _find_daily_work_row(
    date: str,
    student_name: str,
    father_name: str,
    teacher_username: str,
):
    """Cached DailyWork DataFrame سے record row تلاش کریں۔"""
    worksheet = _get_or_create_worksheet(
        config.SHEET_DAILY_WORK,
        config.DAILY_WORK_HEADERS,
    )
    df = get_all_daily_work()

    for dataframe_index, record in df.reset_index(drop=True).iterrows():
        if (
            _normalise(record.get("Date")) == _normalise(date)
            and _normalise(record.get("StudentName"))
            == _normalise(student_name)
            and _normalise(record.get("FatherName"))
            == _normalise(father_name)
            and _normalise(record.get("TeacherUsername"))
            == _normalise(teacher_username)
        ):
            return worksheet, dataframe_index + 2

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
    manzil_juz: str = "",
    manzil_amount: str = "",
    manzil_half: str = "",
    pao_juz: str = "",
    pao_quarter: str = "",
    remarks: str = "",
) -> bool:
    """سبق، سبقی، منزل، پاؤ اور کیفیت سمیت مکمل record update کریں۔"""
    from utils import now_time_str

    worksheet, row_number = _find_daily_work_row(
        date,
        student_name,
        father_name,
        teacher_username,
    )

    if row_number is None:
        st.error("⚠️ تعلیمی record نہیں ملا۔")
        return False

    actual_headers = _get_cached_headers(
        worksheet,
        config.DAILY_WORK_HEADERS,
    )

    record = {
        "Date": date,
        "StudentName": student_name,
        "FatherName": father_name,
        "TeacherUsername": teacher_username,
        "TeacherName": teacher_name,
        "SabaqSurah": sabaq_surah,
        "SabaqAyah": sabaq_ayah,
        "SabqiSurah": sabqi_surah,
        "SabqiAyah": sabqi_ayah,
        "ManzilJuz": manzil_juz,
        "ManzilAmount": manzil_amount,
        "ManzilHalf": manzil_half,
        "PaoJuz": pao_juz,
        "PaoQuarter": pao_quarter,
        "Remarks": remarks,
        "TimeSubmitted": now_time_str(),
    }

    values = _row_for_actual_headers(actual_headers, record)

    return _update_row_range(
        worksheet,
        row_number,
        values,
        "تعلیمی record update کرنے",
    )


def delete_daily_work_record(
    date: str,
    student_name: str,
    father_name: str,
    teacher_username: str,
) -> bool:
    """منتخب روزانہ تعلیمی record حذف کریں۔"""
    worksheet, row_number = _find_daily_work_row(
        date,
        student_name,
        father_name,
        teacher_username,
    )

    if row_number is None:
        st.error("⚠️ تعلیمی record نہیں ملا۔")
        return False

    return _delete_row(
        worksheet,
        row_number,
        "تعلیمی record حذف کرنے",
    )


# ==================================================
# Activity Logs
# ==================================================
def get_all_logs() -> pd.DataFrame:
    return read_all_records(
        config.SHEET_LOGS,
        config.LOGS_HEADERS,
    )


def add_log(
    username: str,
    action: str,
) -> bool:
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
        "Log درج کرنے",
    )


# ==================================================
# Settings
# ==================================================
def get_setting(
    key: str,
    default=None,
):
    df = read_all_records(
        config.SHEET_SETTINGS,
        config.SETTINGS_HEADERS,
    )

    if df.empty or "Key" not in df.columns:
        return default

    match = df[
        df["Key"]
        .astype(str)
        .map(_normalise)
        == _normalise(key)
    ]

    if match.empty:
        return default

    return match.iloc[0].get(
        "Value",
        default,
    )


def set_setting(
    key: str,
    value: str,
) -> bool:
    worksheet = _get_or_create_worksheet(
        config.SHEET_SETTINGS,
        config.SETTINGS_HEADERS,
    )

    settings_df = read_all_records(
        config.SHEET_SETTINGS,
        config.SETTINGS_HEADERS,
    )
    target_key = _normalise(key)

    for dataframe_index, record in (
        settings_df.reset_index(drop=True).iterrows()
    ):
        if _normalise(record.get("Key")) == target_key:
            return _update_cell(
                worksheet,
                dataframe_index + 2,
                2,
                _clean(value),
                "Settings update کرنے",
            )

    return _append_row(
        worksheet,
        [
            _clean(key),
            _clean(value),
        ],
        "نئی setting شامل کرنے",
    )
