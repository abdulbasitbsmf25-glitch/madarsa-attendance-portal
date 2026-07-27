# auth.py
"""
تصدیقِ ہویت کا مکمل نظام

یہ فائل لاگ اِن، لاگ آؤٹ، سیشن مینجمنٹ، کردار کی جانچ
اور پاس ورڈ کی تبدیلی کو سنبھالتی ہے۔
"""

from __future__ import annotations

from typing import Optional, Tuple

import streamlit as st

import config
import sheets
from utils import (
    hash_password as _hash_password,
    verify_password as _verify_password,
)


# ==================================================
# پاس ورڈ ہیشنگ
# ==================================================
def hash_password(password: str) -> str:
    """خام پاس ورڈ کو محفوظ ہیش میں تبدیل کریں۔"""
    return _hash_password(password)


def verify_password(password: str, hashed: str) -> bool:
    """خام پاس ورڈ کا محفوظ شدہ ہیش کے ساتھ موازنہ کریں۔"""
    if not password or not hashed:
        return False

    try:
        return bool(_verify_password(password, hashed))
    except Exception:
        return False


def _get_password_hash(user: dict) -> str:
    """
    صارف ریکارڈ سے پاس ورڈ ہیش حاصل کریں۔

    نئے اور پرانے دونوں ممکنہ کالم ناموں کے ساتھ compatibility رکھی گئی ہے۔
    """
    return str(
        user.get("PasswordHash")
        or user.get("Password")
        or ""
    ).strip()


def _normalize_role(role: object) -> str:
    """کردار کو محفوظ اور یکساں شکل میں تبدیل کریں۔"""
    return str(role or "").strip().lower()


def _roles_match(role_a: object, role_b: object) -> bool:
    """دو کرداروں کا case-insensitive موازنہ کریں۔"""
    return _normalize_role(role_a) == _normalize_role(role_b)


# ==================================================
# لاگ اِن
# ==================================================
def login(username: str, password: str) -> Tuple[bool, str]:
    """
    صارف نام اور پاس ورڈ کی تصدیق کریں۔

    واپسی:
        (کامیابی، اردو پیغام)
    """
    clean_username = str(username or "").strip()

    if not clean_username:
        return False, "براہ کرم صارف نام درج کریں۔"

    if not password:
        return False, "براہ کرم پاس ورڈ درج کریں۔"

    try:
        user = sheets.get_user(clean_username)
    except Exception:
        return False, "صارف کی معلومات حاصل کرنے میں خرابی پیش آئی۔"

    if not user:
        return False, "صارف نام موجود نہیں ہے۔ براہ کرم دوبارہ چیک کریں۔"

    active_value = str(user.get("Active", "TRUE")).strip().upper()
    if active_value in {"FALSE", "0", "NO", "N", "OFF", ""}:
        return (
            False,
            "آپ کا اکاؤنٹ غیر فعال ہے۔ براہ کرم منتظم سے رابطہ کریں۔",
        )

    stored_hash = _get_password_hash(user)
    if not stored_hash:
        return False, "اس صارف کا پاس ورڈ محفوظ نہیں ہے۔ منتظم سے رابطہ کریں۔"

    if not verify_password(password, stored_hash):
        return False, "پاس ورڈ درست نہیں ہے۔ براہ کرم دوبارہ کوشش کریں۔"

    saved_username = str(
        user.get("Username")
        or clean_username
    ).strip()

    full_name = str(
        user.get("FullName")
        or user.get("Name")
        or saved_username
    ).strip()

    role = str(user.get("Role") or "").strip()

    if not role:
        return False, "اس صارف کا کردار مقرر نہیں ہے۔ منتظم سے رابطہ کریں۔"

    st.session_state[config.SESSION_LOGGED_IN] = True
    st.session_state[config.SESSION_USERNAME] = saved_username
    st.session_state[config.SESSION_FULLNAME] = full_name
    st.session_state[config.SESSION_ROLE] = role

    try:
        sheets.add_log(saved_username, "لاگ ان ہوا")
    except Exception:
        # لاگ کی خرابی کامیاب لاگ اِن کو نہیں روکے گی۔
        pass

    return True, f"خوش آمدید، {full_name}!"


# ==================================================
# لاگ آؤٹ
# ==================================================
def logout() -> None:
    """موجودہ صارف کو محفوظ انداز میں لاگ آؤٹ کریں۔"""
    username = current_username()

    if username:
        try:
            sheets.add_log(username, "لاگ آؤٹ ہوا")
        except Exception:
            pass

    session_keys = (
        config.SESSION_LOGGED_IN,
        config.SESSION_USERNAME,
        config.SESSION_FULLNAME,
        config.SESSION_ROLE,
        "sidebar_menu",
    )

    for key in session_keys:
        st.session_state.pop(key, None)


# ==================================================
# سیشن اور کردار کی جانچ
# ==================================================
def is_logged_in() -> bool:
    """چیک کریں کہ کوئی صارف لاگ اِن ہے یا نہیں۔"""
    return bool(st.session_state.get(config.SESSION_LOGGED_IN, False))


def is_admin() -> bool:
    """چیک کریں کہ موجودہ صارف منتظم ہے یا نہیں۔"""
    return (
        is_logged_in()
        and _roles_match(
            st.session_state.get(config.SESSION_ROLE),
            config.ROLE_ADMIN,
        )
    )


def is_teacher() -> bool:
    """چیک کریں کہ موجودہ صارف استاد ہے یا نہیں۔"""
    return (
        is_logged_in()
        and _roles_match(
            st.session_state.get(config.SESSION_ROLE),
            config.ROLE_TEACHER,
        )
    )


def get_current_user() -> Optional[dict]:
    """
    موجودہ صارف کی معلومات واپس کریں۔

    ساخت:
        {
            "username": ...,
            "fullname": ...,
            "role": ...
        }
    """
    if not is_logged_in():
        return None

    return {
        "username": st.session_state.get(config.SESSION_USERNAME),
        "fullname": st.session_state.get(config.SESSION_FULLNAME),
        "role": st.session_state.get(config.SESSION_ROLE),
    }


def current_username() -> Optional[str]:
    """موجودہ صارف نام واپس کریں۔"""
    value = st.session_state.get(config.SESSION_USERNAME)
    return str(value).strip() if value not in (None, "") else None


def current_fullname() -> Optional[str]:
    """موجودہ صارف کا پورا نام واپس کریں۔"""
    value = st.session_state.get(config.SESSION_FULLNAME)
    return str(value).strip() if value not in (None, "") else None


def current_role() -> Optional[str]:
    """موجودہ صارف کا کردار واپس کریں۔"""
    value = st.session_state.get(config.SESSION_ROLE)
    return str(value).strip() if value not in (None, "") else None


# ==================================================
# رسائی کنٹرول
# ==================================================
def require_login() -> None:
    """صرف لاگ اِن صارف کو صفحہ استعمال کرنے دیں۔"""
    if not is_logged_in():
        st.error("⚠️ براہ کرم پہلے لاگ ان کریں۔")
        st.stop()


def require_admin() -> None:
    """صرف منتظم کو صفحہ استعمال کرنے دیں۔"""
    require_login()

    if not is_admin():
        st.error("🚫 اس صفحے تک رسائی صرف منتظم کے لیے ہے۔")
        st.stop()


def require_teacher() -> None:
    """صرف استاد کو صفحہ استعمال کرنے دیں۔"""
    require_login()

    if not is_teacher():
        st.error("🚫 اس صفحے تک رسائی صرف استاد کے لیے ہے۔")
        st.stop()


def require_admin_or_teacher() -> None:
    """منتظم یا استاد، دونوں کو رسائی دیں۔"""
    require_login()

    if not (is_admin() or is_teacher()):
        st.error("🚫 آپ کو اس صفحے تک رسائی حاصل نہیں ہے۔")
        st.stop()


# ==================================================
# کردار کے مطابق ڈیفالٹ صفحہ
# ==================================================
def get_default_page_for_role() -> str:
    """لاگ اِن کے بعد کردار کے مطابق ابتدائی صفحہ واپس کریں۔"""
    if is_admin():
        return "ڈیش بورڈ"

    if is_teacher():
        return "ڈیش بورڈ"

    return "لاگ ان"


# ==================================================
# اپنا پاس ورڈ تبدیل کرنا
# ==================================================
def change_own_password(
    current_password: str,
    new_password: str,
) -> Tuple[bool, str]:
    """
    موجودہ لاگ اِن صارف کا پاس ورڈ تبدیل کریں۔
    """
    username = current_username()

    if not username:
        return False, "آپ لاگ ان نہیں ہیں۔"

    if not current_password:
        return False, "موجودہ پاس ورڈ درج کریں۔"

    clean_new_password = str(new_password or "").strip()

    if len(clean_new_password) < 4:
        return False, "نیا پاس ورڈ کم از کم 4 حروف پر مشتمل ہونا چاہیے۔"

    if current_password == clean_new_password:
        return False, "نیا پاس ورڈ موجودہ پاس ورڈ سے مختلف ہونا چاہیے۔"

    try:
        user = sheets.get_user(username)
    except Exception:
        return False, "صارف کی معلومات حاصل کرنے میں خرابی پیش آئی۔"

    if not user:
        return False, "صارف نہیں ملا۔"

    stored_hash = _get_password_hash(user)
    if not verify_password(current_password, stored_hash):
        return False, "موجودہ پاس ورڈ درست نہیں ہے۔"

    try:
        success = sheets.update_user_password(
            username,
            clean_new_password,
        )
    except Exception:
        success = False

    if not success:
        return False, "پاس ورڈ تبدیل کرنے میں خرابی پیش آئی۔"

    try:
        sheets.add_log(username, "پاس ورڈ تبدیل کیا")
    except Exception:
        pass

    return True, "پاس ورڈ کامیابی سے تبدیل ہو گیا۔"