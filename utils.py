# utils.py
"""
عمومی مددگار فنکشنز (Utility Functions)
==================================================
یہ فائل پورے مدرسہ حاضری پورٹل میں استعمال ہونے والے مشترکہ فنکشنز فراہم کرتی ہے:

    - پاس ورڈ ہیشنگ اور تصدیق
    - تاریخ اور وقت کی فارمیٹنگ
    - RTL اور اردو تھیم
    - اعداد و شمار کے کارڈ
    - کامیابی، خرابی، تنبیہ اور معلوماتی پیغامات
    - تصدیقی بٹن
    - عمومی ان پٹ validation
    - بنیادی رسائی کنٹرول کے compatibility helpers

اہم نوٹ:
    - طالب علم کی شناخت StudentName + FatherName + AssignedTeacher سے ہوتی ہے۔
    - RollNumber مکمل طور پر ختم کیا جا چکا ہے۔
    - مرکزی رسائی کنٹرول auth.py میں موجود ہے۔
"""

from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Any, Optional

import streamlit as st
from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)

import config


# ==================================================
# پاس ورڈ ہیشنگ اور تصدیق
# ==================================================
def hash_password(password: str) -> str:
    """
    خام پاس ورڈ کو محفوظ ہیش میں تبدیل کریں۔

    خالی پاس ورڈ قبول نہیں کیا جاتا۔
    """
    clean_password = str(password or "").strip()

    if not clean_password:
        raise ValueError("پاس ورڈ خالی نہیں ہو سکتا۔")

    return generate_password_hash(
        clean_password,
        method="pbkdf2:sha256",
    )


def verify_password(password: str, hashed: str) -> bool:
    """
    خام پاس ورڈ کا محفوظ شدہ ہیش کے ساتھ موازنہ کریں۔

    غلط یا خالی ہیش کی صورت میں exception کے بجائے False واپس کیا جاتا ہے۔
    """
    clean_password = str(password or "")
    clean_hash = str(hashed or "").strip()

    if not clean_password or not clean_hash:
        return False

    try:
        return bool(
            check_password_hash(
                clean_hash,
                clean_password,
            )
        )
    except (ValueError, TypeError):
        return False


# ==================================================
# تاریخ اور وقت
# ==================================================
def today_str() -> str:
    """آج کی تاریخ YYYY-MM-DD میں واپس کریں۔"""
    return datetime.now().strftime("%Y-%m-%d")


def now_time_str() -> str:
    """موجودہ وقت HH:MM:SS میں واپس کریں۔"""
    return datetime.now().strftime("%H:%M:%S")


def current_month_str() -> str:
    """موجودہ مہینہ YYYY-MM میں واپس کریں۔"""
    return datetime.now().strftime("%Y-%m")


def now_datetime_str() -> str:
    """موجودہ تاریخ اور وقت YYYY-MM-DD HH:MM:SS میں واپس کریں۔"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_date(
    date_value: Any,
    output_format: str = "%d-%m-%Y",
) -> str:
    """
    تاریخ کو صارف کے لیے خوبصورت فارمیٹ میں تبدیل کریں۔

    قابل قبول input:
        - YYYY-MM-DD string
        - datetime object
        - date object
    """
    if date_value in (None, ""):
        return ""

    if isinstance(date_value, datetime):
        return date_value.strftime(output_format)

    if isinstance(date_value, date):
        return date_value.strftime(output_format)

    clean_value = str(date_value).strip()

    accepted_formats = (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d/%m/%Y",
    )

    for input_format in accepted_formats:
        try:
            parsed = datetime.strptime(
                clean_value,
                input_format,
            )
            return parsed.strftime(output_format)
        except ValueError:
            continue

    return clean_value


def format_time(
    time_value: Any,
    output_format: str = "%I:%M %p",
) -> str:
    """
    وقت کو 12 گھنٹے یا مطلوبہ فارمیٹ میں تبدیل کریں۔
    """
    if time_value in (None, ""):
        return ""

    if isinstance(time_value, datetime):
        return time_value.strftime(output_format)

    clean_value = str(time_value).strip()

    accepted_formats = (
        "%H:%M:%S",
        "%H:%M",
        "%I:%M %p",
    )

    for input_format in accepted_formats:
        try:
            parsed = datetime.strptime(
                clean_value,
                input_format,
            )
            return parsed.strftime(output_format)
        except ValueError:
            continue

    return clean_value


# ==================================================
# CSS اور عمومی تھیم
# ==================================================
def apply_global_styles() -> None:
    """
    پورے پورٹل پر RTL، اردو فونٹ اور اسلامی تھیم لاگو کریں۔

    app.py میں بیرونی assets/style.css بھی استعمال ہو سکتی ہے۔
    یہ فنکشن compatibility اور fallback styling کے لیے محفوظ رکھا گیا ہے۔
    """
    primary = getattr(config, "COLOR_PRIMARY", "#176B45")
    primary_light = getattr(config, "COLOR_PRIMARY_LIGHT", "#F4FBF7")
    accent = getattr(config, "COLOR_ACCENT", "#D4AF37")
    white = getattr(config, "COLOR_WHITE", "#FFFFFF")
    text = getattr(config, "COLOR_TEXT", "#1F2937")

    st.markdown(
        f"""
        <style>
        @import url(
            'https://fonts.googleapis.com/css2?family=Noto+Nastaliq+Urdu:wght@400;600;700&family=Noto+Sans+Arabic:wght@400;600;700&display=swap'
        );

        html,
        body,
        [class*="css"],
        [data-testid="stAppViewContainer"] {{
            direction: rtl;
            text-align: right;
            font-family:
                'Noto Nastaliq Urdu',
                'Noto Sans Arabic',
                sans-serif !important;
        }}

        .stApp {{
            background-color: {primary_light};
        }}

        section[data-testid="stSidebar"] {{
            background-color: {primary};
            direction: rtl;
        }}

        section[data-testid="stSidebar"] * {{
            color: {white} !important;
        }}

        .stButton > button,
        .stFormSubmitButton > button {{
            background-color: {primary};
            color: {white};
            border-radius: 10px;
            border: none;
            padding: 0.5rem 1.2rem;
            font-weight: 600;
            font-size: 1rem;
            transition: 0.2s ease;
        }}

        .stButton > button:hover,
        .stFormSubmitButton > button:hover {{
            background-color: {accent};
            color: {text};
        }}

        h1,
        h2,
        h3,
        h4 {{
            color: {primary};
            font-family:
                'Noto Nastaliq Urdu',
                'Noto Sans Arabic',
                sans-serif !important;
        }}

        .custom-card,
        .stat-card {{
            background-color: {white};
            border-radius: 16px;
            padding: 1.2rem;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
            border-right: 6px solid {primary};
            margin-bottom: 1rem;
            text-align: center;
        }}

        .stat-icon {{
            font-size: 1.8rem;
            margin-bottom: 0.35rem;
        }}

        .stat-value {{
            color: {primary};
            font-size: 2rem;
            font-weight: 700;
            line-height: 1.4;
        }}

        .stat-title {{
            color: #555;
            font-size: 1rem;
            margin-top: 0.2rem;
        }}

        .stDataFrame,
        table {{
            direction: rtl;
            text-align: right;
        }}

        input,
        textarea,
        select {{
            direction: rtl;
            text-align: right;
        }}

        .login-box {{
            background-color: {white};
            border-radius: 20px;
            padding: 2.5rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.10);
            max-width: 520px;
            margin: 2rem auto;
        }}

        @media (max-width: 640px) {{
            .login-box {{
                padding: 1.25rem;
                margin: 1rem auto;
            }}

            .stat-value {{
                font-size: 1.5rem;
            }}

            .stat-title {{
                font-size: 0.9rem;
            }}
        }}

        footer {{
            visibility: hidden;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==================================================
# UI مددگار
# ==================================================
def render_stat_card(
    title: str,
    value: Any,
    icon: str = "📌",
) -> None:
    """
    ایک محفوظ اور reusable اعداد و شمار کا کارڈ دکھائیں۔
    """
    safe_title = escape(str(title or ""))
    safe_value = escape(str(value if value is not None else ""))
    safe_icon = escape(str(icon or "📌"))

    st.markdown(
        f"""
        <div class="stat-card">
            <div class="stat-icon">{safe_icon}</div>
            <div class="stat-value">{safe_value}</div>
            <div class="stat-title">{safe_title}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_title(
    title: str,
    icon: str = "",
) -> None:
    """صفحے کے حصے کا یکساں عنوان دکھائیں۔"""
    safe_title = escape(str(title or ""))
    safe_icon = escape(str(icon or ""))

    st.markdown(
        f"### {safe_icon} {safe_title}".strip()
    )


# ==================================================
# پیغامات
# ==================================================
def success_message(message: str) -> None:
    """کامیابی کا اردو پیغام دکھائیں۔"""
    st.success(f"✅ {message}")


def error_message(message: str) -> None:
    """خرابی کا اردو پیغام دکھائیں۔"""
    st.error(f"⚠️ {message}")


def warning_message(message: str) -> None:
    """تنبیہی اردو پیغام دکھائیں۔"""
    st.warning(f"⚠️ {message}")


def info_message(message: str) -> None:
    """معلوماتی اردو پیغام دکھائیں۔"""
    st.info(f"ℹ️ {message}")


# پرانے modules کے ساتھ compatibility aliases
show_success = success_message
show_error = error_message
show_warning = warning_message
show_info = info_message


def confirmation_message(
    message: str,
    key: str,
) -> bool:
    """
    حساس عمل سے پہلے تصدیق حاصل کریں۔

    True صرف اسی وقت واپس ہوگا جب صارف 'ہاں' دبائے۔
    """
    warning_message(message)

    yes_column, no_column = st.columns(2)

    with yes_column:
        yes_clicked = st.button(
            "✅ ہاں، جاری رکھیں",
            key=f"{key}_yes",
            use_container_width=True,
        )

    with no_column:
        st.button(
            "❌ منسوخ کریں",
            key=f"{key}_no",
            use_container_width=True,
        )

    return bool(yes_clicked)


# ==================================================
# عمومی Input Validation
# ==================================================
def is_non_empty(value: Any) -> bool:
    """چیک کریں کہ قدر خالی نہیں ہے۔"""
    return bool(str(value or "").strip())


def clean_text(value: Any) -> str:
    """عام متن کو محفوظ طور پر string میں تبدیل اور trim کریں۔"""
    return str(value or "").strip()


def is_valid_phone(phone: str) -> bool:
    """
    فون نمبر کی بنیادی جانچ کریں۔

    spaces، dash، plus اور brackets نظر انداز کیے جاتے ہیں۔
    """
    clean_phone = str(phone or "").strip()

    for character in ("-", " ", "+", "(", ")"):
        clean_phone = clean_phone.replace(character, "")

    return clean_phone.isdigit() and 7 <= len(clean_phone) <= 15


def is_valid_name(name: str, minimum_length: int = 2) -> bool:
    """طالب علم، والد یا استاد کے نام کی بنیادی جانچ کریں۔"""
    clean_name = clean_text(name)
    return len(clean_name) >= minimum_length


def is_valid_student_identity(
    student_name: str,
    father_name: str,
) -> bool:
    """
    طالب علم کی نئی شناخت StudentName + FatherName کے مطابق چیک کریں۔
    """
    return (
        is_valid_name(student_name)
        and is_valid_name(father_name)
    )


def normalize_username(username: str) -> str:
    """صارف نام کو lowercase اور trim کریں۔"""
    return clean_text(username).lower()


# ==================================================
# رسائی کنٹرول Compatibility Helpers
# ==================================================
def _roles_match(role_a: Any, role_b: Any) -> bool:
    """کرداروں کا case-insensitive موازنہ کریں۔"""
    return clean_text(role_a).lower() == clean_text(role_b).lower()


def require_login() -> None:
    """
    لاگ اِن نہ ہونے کی صورت میں صفحہ روک دیں۔

    نئی فائلوں میں auth.require_login() کو ترجیح دی جائے۔
    """
    if not st.session_state.get(
        config.SESSION_LOGGED_IN,
        False,
    ):
        error_message("براہ کرم پہلے لاگ ان کریں۔")
        st.stop()


def require_admin() -> None:
    """
    صرف منتظم کو رسائی دیں۔

    نئی فائلوں میں auth.require_admin() کو ترجیح دی جائے۔
    """
    require_login()

    current_role = st.session_state.get(
        config.SESSION_ROLE
    )

    if not _roles_match(
        current_role,
        config.ROLE_ADMIN,
    ):
        error_message(
            "معذرت، اس صفحے تک رسائی صرف منتظم کے لیے ہے۔"
        )
        st.stop()


def require_teacher() -> None:
    """
    صرف استاد کو رسائی دیں۔

    نئی فائلوں میں auth.require_teacher() کو ترجیح دی جائے۔
    """
    require_login()

    current_role = st.session_state.get(
        config.SESSION_ROLE
    )

    if not _roles_match(
        current_role,
        config.ROLE_TEACHER,
    ):
        error_message(
            "معذرت، اس صفحے تک رسائی صرف استاد کے لیے ہے۔"
        )
        st.stop()


def require_admin_or_teacher() -> None:
    """منتظم یا استاد دونوں کو رسائی دیں۔"""
    require_login()

    current_role = st.session_state.get(
        config.SESSION_ROLE
    )

    allowed = (
        _roles_match(current_role, config.ROLE_ADMIN)
        or _roles_match(current_role, config.ROLE_TEACHER)
    )

    if not allowed:
        error_message(
            "معذرت، آپ کو اس صفحے تک رسائی حاصل نہیں ہے۔"
        )
        st.stop()