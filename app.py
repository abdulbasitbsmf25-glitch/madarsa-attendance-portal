# app.py
"""
مرکزی ایپلیکیشن فائل (Main Entry Point)
==================================================
یہ فائل مدرسہ حاضری پورٹل کا مرکزی دروازہ ہے۔ اس کی ذمہ داریاں:

    1) Streamlit صفحہ کی بنیادی ترتیب (Page Config) لاگو کرنا
    2) ڈیٹا بیس (گوگل شیٹس) کو ایک بار شروع (initialize) کرنا
    3) اگر صارف لاگ ان نہیں ہے تو لاگ ان صفحہ دکھانا
    4) لاگ ان کے بعد صارف کے کردار (Admin/Teacher) کے مطابق
       سائیڈ بار نیویگیشن اور مناسب صفحہ دکھانا
    5) غیر مجاز رسائی کو مکمل طور پر روکنا

اس فائل کو چلانے کا طریقہ:
    streamlit run app.py
"""
import os
import streamlit as st

def load_css():
    with open("assets/style.css", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)






import config
import sheets
import auth
import login
#from utils import apply_global_styles

# صفحات (Pages) کے ماڈیولز
import dashboard
import students
import attendance
import reports
import settings
import logs


# ==================================================
# 1) Streamlit صفحہ کی بنیادی ترتیب
# ==================================================
st.set_page_config(
    page_title=config.APP_TITLE,
    page_icon="🕌",
    layout="wide",
    initial_sidebar_state="expanded",
)
load_css()
# RTL، اردو فونٹ اور اسلامی سبز و سفید تھیم پوری ایپ پر لاگو کریں
#apply_global_styles()


# ==================================================
# 2) ڈیٹا بیس (گوگل شیٹس) کو ایک بار شروع کریں
# ==================================================
if "db_initialized" not in st.session_state:
    with st.spinner("سسٹم تیار کیا جا رہا ہے..."):
        sheets.initialize_database()
    st.session_state["db_initialized"] = True


# ==================================================
# 3) اگر صارف لاگ ان نہیں ہے تو لاگ ان صفحہ دکھائیں اور رک جائیں
# ==================================================
if not auth.is_logged_in():
    login.render_login_page()
    st.stop()


# ==================================================
# 4) سائیڈ بار: لوگو، اسکول کا نام، صارف کی معلومات، نیویگیشن، لاگ آؤٹ
# ==================================================
def render_sidebar() -> str:
    """
    مکمل سائیڈ بار بنائیں اور صارف کے منتخب کردہ صفحے کا نام واپس کریں۔
    مینو صرف اسی صارف کے کردار (Admin/Teacher) کے مطابق دکھایا جاتا ہے۔
    """

    school_name = sheets.get_setting(
        "SchoolName",
        config.DEFAULT_SCHOOL_NAME,
    )

    user = auth.get_current_user()

    with st.sidebar:

        # ---------------- مدرسہ کا لوگو ----------------
        school_html = (
            '<div class="sidebar-school">'
            '<div class="sidebar-school-icon">🕌</div>'
            f'<div class="sidebar-school-name">{school_name}</div>'
            '</div>'
        )

        st.markdown(
            school_html,
            unsafe_allow_html=True,
        )

        # ---------------- صارف کی معلومات ----------------
        profile_html = (
            '<div class="simple-sidebar-profile">'
            '<div class="simple-avatar">👤</div>'
            f'<div class="simple-user-name">{user["fullname"]}</div>'
            f'<div class="simple-user-role">{user["role"]}</div>'
            '<div class="simple-online">● آن لائن</div>'
            '</div>'
        )

        st.markdown(
            profile_html,
            unsafe_allow_html=True,
        )

        # ---------------- مینو ----------------
        if auth.is_admin():
            menu_options = [
                "ڈیش بورڈ",
                "طلباء کا انتظام",
                "حاضری کا مکمل ریکارڈ",
                "رپورٹس",
                "سرگرمی لاگز",
                "ترتیبات",
            ]
        else:
            menu_options = [
                "حاضری درج کریں",
                "رپورٹس",
            ]

        st.markdown(
            '<div class="sidebar-menu-title">📋 مینو</div>',
            unsafe_allow_html=True,
        )

        selected_page = st.radio(
            "صفحہ منتخب کریں",
            menu_options,
            label_visibility="collapsed",
            key="sidebar_menu",
        )

        st.markdown(
            '<div class="sidebar-divider"></div>',
            unsafe_allow_html=True,
        )

        # ---------------- لاگ آؤٹ ----------------
        if st.button(
            "🚪 لاگ آؤٹ",
            use_container_width=True,
            key="sidebar_logout",
        ):
            auth.logout()
            st.success("✅ آپ کامیابی سے لاگ آؤٹ ہو گئے۔")
            st.rerun()

    return selected_page


# ==================================================
# 5) صفحہ روٹنگ (Page Routing) — منتخب کردہ صفحہ دکھائیں
# ==================================================
def route_to_page(page_name: str):
    """
    منتخب کردہ صفحے کے نام کی بنیاد پر درست ماڈیول کا فنکشن کال کریں۔
    ہر صفحہ اپنے اندر بھی require_admin() / require_teacher() کے ذریعے
    اضافی حفاظتی تصدیق کرتا ہے (Defense in Depth)۔
    """
    if page_name == "ڈیش بورڈ":
        dashboard.render_dashboard()

    elif page_name == "طلباء کا انتظام":
        students.render_students_page()

    elif page_name == "حاضری کا مکمل ریکارڈ":
        attendance.render_admin_attendance_page()

    elif page_name == "رپورٹس":
        reports.render_reports_page()

    elif page_name == "سرگرمی لاگز":
        logs.render_logs_page()

    elif page_name == "ترتیبات":
        settings.render_settings_page()

    elif page_name == "حاضری درج کریں":
        attendance.render_mark_attendance_page()

    else:
        st.error("⚠️ یہ صفحہ موجود نہیں ہے۔")


# ==================================================
# 6) مرکزی ایگزیکیوشن (Main Execution)
# ==================================================
selected = render_sidebar()
route_to_page(selected)