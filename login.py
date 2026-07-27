# login.py
"""
لاگ ان صفحہ (Login Page)
==================================================
یہ فائل مدرسہ حاضری پورٹل کا مرکزی لاگ ان صفحہ بناتی ہے۔

خصوصیات:
    - مکمل اردو انٹرفیس
    - RTL ترتیب کے ساتھ مطابقت
    - auth.py کے ذریعے تصدیقِ ہویت
    - خالی فیلڈز کی جانچ
    - کامیابی اور ناکامی کے واضح اردو پیغامات
    - کامیاب لاگ ان کے بعد خودکار ری لوڈ
    - اگر صارف پہلے سے لاگ ان ہو تو لاگ ان فارم دوبارہ نہیں دکھایا جاتا
    - اسکول کے نام کو محفوظ انداز میں HTML میں دکھایا جاتا ہے
"""

from __future__ import annotations

from html import escape
from textwrap import dedent

import streamlit as st

import auth
import config
import sheets


# ==================================================
# مددگار فنکشنز
# ==================================================
def _get_school_name() -> str:
    """
    Settings شیٹ سے مدرسہ کا نام حاصل کریں۔

    اگر سیٹنگ موجود نہ ہو یا خالی ہو تو config.py میں موجود
    ڈیفالٹ نام استعمال کیا جائے گا۔
    """
    try:
        school_name = sheets.get_setting(
            "SchoolName",
            config.DEFAULT_SCHOOL_NAME,
        )
    except Exception:
        school_name = config.DEFAULT_SCHOOL_NAME

    school_name = str(
        school_name or config.DEFAULT_SCHOOL_NAME
    ).strip()

    if not school_name:
        school_name = config.DEFAULT_SCHOOL_NAME

    return school_name


def _render_login_header(school_name: str) -> None:
    """
    لاگ ان صفحے کا لوگو، مدرسہ کا نام اور خوش آمدیدی پیغام دکھائیں۔
    """
    safe_school_name = escape(school_name)

    header_html = dedent(
        f"""
        <div style="
            text-align: center;
            margin-top: 2rem;
            margin-bottom: 1rem;
        ">
            <div style="
                font-size: 3.2rem;
                line-height: 1;
                margin-bottom: 0.6rem;
            ">
                🕌
            </div>

            <h1 style="
                margin: 0;
                padding: 0;
            ">
                {safe_school_name}
            </h1>

            <p style="
                color: #555;
                font-size: 1.1rem;
                margin-top: 0.6rem;
                margin-bottom: 0;
            ">
                مدرسہ کے نظام میں خوش آمدید
            </p>
        </div>
        """
    ).strip()

    st.html(header_html)


def _render_security_note() -> None:
    """
    لاگ ان معلومات کی حفاظت سے متعلق مختصر نوٹ دکھائیں۔
    """
    security_html = dedent(
        """
        <p style="
            text-align: center;
            color: #888;
            font-size: 0.85rem;
            margin-top: 1rem;
        ">
            براہ کرم اپنی لاگ ان معلومات کسی کے ساتھ شیئر نہ کریں۔
        </p>
        """
    ).strip()

    st.html(security_html)


# ==================================================
# مرکزی لاگ ان صفحہ
# ==================================================
def render_login_page() -> None:
    """
    لاگ ان کا مکمل صفحہ دکھائیں۔

    اگر صارف پہلے سے لاگ ان ہے تو یہ فنکشن فوراً واپس ہو جاتا ہے۔
    app.py اس کے بعد صارف کے کردار کے مطابق مناسب صفحہ دکھاتا ہے۔
    """

    # ==================================================
    # 1) پہلے سے لاگ ان صارف
    # ==================================================
    if auth.is_logged_in():
        return

    # ==================================================
    # 2) مدرسہ کا نام حاصل کریں
    # ==================================================
    school_name = _get_school_name()

    # ==================================================
    # 3) Responsive درمیان والی ترتیب
    # ==================================================
    left_column, center_column, right_column = st.columns(
        [1, 2, 1]
    )

    # صرف درمیان والا کالم استعمال ہوگا
    with center_column:

        # ---------------- لوگو اور عنوان ----------------
        _render_login_header(school_name)

        # ---------------- لاگ ان کارڈ ----------------
        st.subheader("🔐 لاگ ان کریں")

        # ==================================================
        # 4) لاگ ان فارم
        # ==================================================
        with st.form(
            "login_form",
            clear_on_submit=False,
        ):
            username = st.text_input(
                "صارف نام",
                placeholder="اپنا صارف نام درج کریں",
                key="login_username",
                autocomplete="username",
            )

            password = st.text_input(
                "پاس ورڈ",
                type="password",
                placeholder="اپنا پاس ورڈ درج کریں",
                key="login_password",
                autocomplete="current-password",
            )

            submitted = st.form_submit_button(
                "لاگ ان کریں",
                use_container_width=True,
            )

            # ==================================================
            # 5) فارم جمع ہونے پر تصدیق
            # ==================================================
            if submitted:
                clean_username = str(
                    username or ""
                ).strip()

                # خالی صارف نام
                if not clean_username:
                    st.error(
                        "⚠️ براہ کرم صارف نام درج کریں۔"
                    )

                # خالی پاس ورڈ
                elif not password:
                    st.error(
                        "⚠️ براہ کرم پاس ورڈ درج کریں۔"
                    )

                else:
                    try:
                        with st.spinner(
                            "تصدیق کی جا رہی ہے..."
                        ):
                            success, message = auth.login(
                                clean_username,
                                password,
                            )

                    except Exception:
                        success = False
                        message = (
                            "لاگ ان کے دوران غیر متوقع خرابی پیش آئی۔ "
                            "براہ کرم دوبارہ کوشش کریں۔"
                        )

                    # کامیاب لاگ ان
                    if success:
                        st.success(
                            f"✅ {message}"
                        )

                        # نئی session_state کے مطابق پوری ایپ دوبارہ چلائیں
                        st.rerun()

                    # ناکام لاگ ان
                    else:
                        st.error(
                            f"⚠️ {message}"
                        )

        # ---------------- حفاظتی نوٹ ----------------
        _render_security_note()