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


def _worksheet_headers(
    worksheet,
    expected_headers: list[str],
) -> list[str]:
    """
    Worksheet کے حقیقی headers واپس کریں اور missing headers آخر میں شامل کریں۔

    اس سے پرانی Google Sheet بھی نئے AttendanceSession یا Remarks کالم کے
    ساتھ محفوظ طریقے سے کام کرتی ہے اور data غلط column میں نہیں جاتا۔
    """
    try:
        values = worksheet.get_all_values()
        actual_headers = (
            [_clean(value) for value in values[0]]
            if values
            else []
        )

        if not actual_headers:
            worksheet.append_row(
                expected_headers,
                value_input_option="RAW",
            )
            return list(expected_headers)

        missing_headers = [
            header
            for header in expected_headers
            if header not in actual_headers
        ]

        if missing_headers:
            updated_headers = actual_headers + missing_headers
            last_column = _column_letter(len(updated_headers))
            worksheet.update(
                values=[updated_headers],
                range_name=f"A1:{last_column}1",
            )
            actual_headers = updated_headers

        return actual_headers

    except Exception as error:
        st.error(
            "⚠️ Worksheet headers update کرنے میں خرابی پیش آئی۔"
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
    Cached Google connection صاف کریں۔
    Backup، restore یا manual refresh کے بعد استعمال کریں۔
    """
    get_client.clear()
    get_spreadsheet.clear()


# ==================================================
# 2) Worksheets بنانا اور چیک کرنا
# ==================================================
def _get_or_create_worksheet(
    sheet_name: str,
    headers: list[str],
):
    """
    Worksheet حاصل کریں۔
    موجود نہ ہونے پر نئی Worksheet اور headers بنائیں۔
    """
    spreadsheet = get_spreadsheet()

    try:
        worksheet = spreadsheet.worksheet(
            sheet_name
        )

    except gspread.WorksheetNotFound:
        try:
            worksheet = spreadsheet.add_worksheet(
                title=sheet_name,
                rows=1000,
                cols=max(len(headers), 5),
            )
            worksheet.append_row(
                headers,
                value_input_option="RAW",
            )
            return worksheet

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

    try:
        existing_values = worksheet.get_all_values()

        if not existing_values:
            worksheet.append_row(
                headers,
                value_input_option="RAW",
            )

    except Exception as error:
        st.error(
            f"⚠️ '{sheet_name}' Worksheet پڑھنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        st.stop()

    _worksheet_headers(worksheet, headers)
    return worksheet


def initialize_database():
    """
    تمام مطلوبہ Worksheets بنائیں۔
    Users Worksheet خالی ہونے پر default users شامل کریں۔
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
        records = users_ws.get_all_records()

    except Exception as error:
        st.error(
            "⚠️ Users Worksheet پڑھنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        st.stop()

    if records:
        return

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

    _append_rows(
        users_ws,
        rows,
        "Default users شامل کرنے",
    )


# ==================================================
# 3) عمومی CRUD فنکشنز
# ==================================================
def read_all_records(
    sheet_name: str,
    headers: list[str],
) -> pd.DataFrame:
    """Worksheet کا مکمل data DataFrame میں پڑھیں۔"""
    worksheet = _get_or_create_worksheet(
        sheet_name,
        headers,
    )

    try:
        records = worksheet.get_all_records()

    except Exception as error:
        st.error(
            f"⚠️ '{sheet_name}' سے data پڑھنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return pd.DataFrame(columns=headers)

    return _dataframe_with_headers(
        records,
        headers,
    )


def _append_row(
    worksheet,
    row: list,
    action_desc: str = "Data شامل کرنے",
) -> bool:
    """Worksheet میں ایک نئی row شامل کریں۔"""
    try:
        worksheet.append_row(
            row,
            value_input_option="RAW",
        )
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
    """Worksheet میں کئی rows ایک ساتھ شامل کریں۔"""
    try:
        if rows:
            worksheet.append_rows(
                rows,
                value_input_option="RAW",
            )
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
        worksheet.update_cell(
            row,
            column,
            value,
        )
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
    """Worksheet کی مکمل row کو ایک request میں update کریں۔"""
    try:
        last_column = _column_letter(
            len(values)
        )

        worksheet.update(
            values=[values],
            range_name=(
                f"A{row}:{last_column}{row}"
            ),
        )
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
        worksheet.delete_rows(row)
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
    """Username کے exact match سے Google Sheet row تلاش کریں۔"""
    worksheet = _get_or_create_worksheet(
        config.SHEET_USERS,
        config.USERS_HEADERS,
    )

    try:
        records = worksheet.get_all_records()

    except Exception as error:
        st.error(
            "⚠️ صارف تلاش کرنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return worksheet, None

    target = _normalise(username)

    for dataframe_index, record in enumerate(
        records
    ):
        if _normalise(
            record.get("Username")
        ) == target:
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
    """
    StudentName + FatherName + AssignedTeacher کے exact match سے row تلاش کریں۔
    """
    worksheet = _get_or_create_worksheet(
        config.SHEET_STUDENTS,
        config.STUDENTS_HEADERS,
    )

    try:
        records = worksheet.get_all_records()

    except Exception as error:
        st.error(
            "⚠️ طالب علم تلاش کرنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return worksheet, None

    target_name = _normalise(student_name)
    target_father = _normalise(father_name)
    target_teacher = _normalise(
        assigned_teacher
    )

    for dataframe_index, record in enumerate(
        records
    ):
        same_name = (
            _normalise(
                record.get("StudentName")
            )
            == target_name
        )
        same_father = (
            _normalise(
                record.get("FatherName")
            )
            == target_father
        )
        same_teacher = (
            _normalise(
                record.get("AssignedTeacher")
            )
            == target_teacher
        )

        if (
            same_name
            and same_father
            and same_teacher
        ):
            return (
                worksheet,
                dataframe_index + 2,
            )

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
    actual_headers = _worksheet_headers(
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
    """Date + student + teacher + اختیاری session سے row تلاش کریں۔"""
    worksheet = _get_or_create_worksheet(
        config.SHEET_ATTENDANCE,
        config.ATTENDANCE_HEADERS,
    )

    try:
        records = worksheet.get_all_records()
    except Exception as error:
        st.error(
            "⚠️ حاضری کا record تلاش کرنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return worksheet, None

    for dataframe_index, record in enumerate(records):
        matched = (
            _normalise(record.get("Date")) == _normalise(date)
            and _normalise(record.get("StudentName"))
            == _normalise(student_name)
            and _normalise(record.get("FatherName"))
            == _normalise(father_name)
            and _normalise(record.get("TeacherUsername"))
            == _normalise(teacher_username)
        )

        if (
            matched
            and attendance_session is not None
            and "AttendanceSession" in record
        ):
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

    actual_headers = _worksheet_headers(
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
    actual_headers = _worksheet_headers(
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
    """Date + student + teacher سے تعلیمی work row تلاش کریں۔"""
    worksheet = _get_or_create_worksheet(
        config.SHEET_DAILY_WORK,
        config.DAILY_WORK_HEADERS,
    )

    try:
        records = worksheet.get_all_records()
    except Exception as error:
        st.error(
            "⚠️ تعلیمی record تلاش کرنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return worksheet, None

    for dataframe_index, record in enumerate(records):
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

    actual_headers = _worksheet_headers(
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

    try:
        records = worksheet.get_all_records()

    except Exception as error:
        st.error(
            "⚠️ Settings تلاش کرنے میں خرابی پیش آئی۔"
            f"\n\nتفصیل: {error}"
        )
        return False

    target_key = _normalise(key)

    for dataframe_index, record in enumerate(
        records
    ):
        if _normalise(
            record.get("Key")
        ) == target_key:
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