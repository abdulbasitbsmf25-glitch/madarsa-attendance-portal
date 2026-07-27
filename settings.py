# settings.py
"""
ترتیبات کا صفحہ (Settings Module)
==================================================
یہ صفحہ صرف منتظم (Admin — قاری اسماعیل یا کوئی بھی صارف جس کا کردار "منتظم" ہو)
کے لیے مخصوص ہے۔

اس صفحے کے حصے:
    1) مدرسہ کی معلومات (نام، لوگو، فوٹر)
    2) ایڈمن کا اپنا پاس ورڈ تبدیل کرنا
    3) اساتذہ کا مکمل انتظام (شامل/ترمیم/فعال/غیر فعال/پاس ورڈ ری سیٹ/حذف)
    4) تھیم کی ترتیبات (رنگ)
    5) سسٹم کی معلومات (اعداد و شمار)
    6) بیک اپ کی معلومات

اصول: اس فائل میں گوگل شیٹس کا کوئی براہِ راست لاجک نہیں لکھا گیا — ہر ڈیٹا بیس
عملیہ sheets.py کے ذریعے انجام دیا جاتا ہے۔
"""

import streamlit as st

import config
import sheets
import auth
from utils import (
    require_admin,
    render_stat_card,
    success_message,
    error_message,
    warning_message,
    info_message,
    verify_password,
    is_non_empty,
    now_time_str,
    today_str,
)

def render_settings_page():
    require_admin()

    st.title("⚙️ ترتیبات")
    st.caption("یہاں سے مدرسہ کی معلومات، پاس ورڈ، اساتذہ، تھیم اور سسٹم کی ترتیبات منظم کی جا سکتی ہیں۔")

    tabs = st.tabs(
        [
            "🏫 مدرسہ کی معلومات",
            "🔑 پاس ورڈ تبدیل کریں",
            "👨‍🏫 اساتذہ کا انتظام",
            "🎨 تھیم کی ترتیبات",
            "📊 سسٹم کی معلومات",
            "💾 بیک اپ کی معلومات",
        ]
    )

    with tabs[0]:
        render_madarsa_info_section()
    with tabs[1]:
        render_change_password_section()
    with tabs[2]:
        render_teacher_management_section()
    with tabs[3]:
        render_theme_settings_section()
    with tabs[4]:
        render_system_info_section()
    with tabs[5]:
        render_backup_info_section()


# ==================================================
# 1) مدرسہ کی معلومات
# ==================================================
def render_madarsa_info_section():
    st.subheader("🏫 مدرسہ کی معلومات")

    current_name = sheets.get_setting("SchoolName", config.DEFAULT_SCHOOL_NAME)
    current_footer = sheets.get_setting("FooterText", "")
    current_logo = sheets.get_setting("LogoPath", "")

    with st.form("madarsa_info_form"):
        school_name = st.text_input("مدرسہ کا نام", value=current_name)
        footer_text = st.text_input("فوٹر کا متن (اختیاری)", value=current_footer)
        logo_file = st.file_uploader("مدرسہ کا لوگو اپلوڈ کریں (اختیاری)", type=["png", "jpg", "jpeg"])

        submitted = st.form_submit_button("✅ معلومات محفوظ کریں", use_container_width=True)

        if submitted:
            if not is_non_empty(school_name):
                error_message("مدرسہ کا نام خالی نہیں ہو سکتا۔")
                return

            with st.spinner("معلومات محفوظ کی جا رہی ہیں..."):
                ok1 = sheets.set_setting("SchoolName", school_name.strip())
                ok2 = sheets.set_setting("FooterText", footer_text.strip())

                logo_saved = True
                if logo_file is not None:
                    try:
                        import base64

                        logo_bytes = logo_file.read()
                        encoded = base64.b64encode(logo_bytes).decode("utf-8")
                        logo_saved = sheets.set_setting("LogoBase64", encoded)
                        sheets.set_setting("LogoFileName", logo_file.name)
                    except Exception as e:
                        logo_saved = False
                        error_message(f"لوگو محفوظ کرنے میں خرابی: {e}")

            if ok1 and ok2 and logo_saved:
                sheets.add_log(auth.current_username(), "مدرسہ کی معلومات تبدیل کیں")
                success_message("مدرسہ کی معلومات کامیابی سے محفوظ ہو گئیں۔")
                st.rerun()
            else:
                error_message("کچھ معلومات محفوظ کرنے میں خرابی پیش آئی۔")

    if current_logo or sheets.get_setting("LogoBase64"):
        st.caption("موجودہ لوگو محفوظ شدہ ہے۔ نیا لوگو اپلوڈ کر کے تبدیل کیا جا سکتا ہے۔")


# ==================================================
# 2) ایڈمن کا پاس ورڈ تبدیل کریں
# ==================================================
def render_change_password_section():
    st.subheader("🔑 اپنا پاس ورڈ تبدیل کریں")
    info_message("نیا پاس ورڈ کم از کم 8 حروف پر مشتمل ہونا چاہیے۔")

    with st.form("change_password_form", clear_on_submit=True):
        current_password = st.text_input("موجودہ پاس ورڈ", type="password")
        new_password = st.text_input("نیا پاس ورڈ", type="password")
        confirm_password = st.text_input("نئے پاس ورڈ کی تصدیق کریں", type="password")

        submitted = st.form_submit_button("✅ پاس ورڈ تبدیل کریں", use_container_width=True)

        if submitted:
            username = auth.current_username()
            user = sheets.get_user(username)

            if user is None:
                error_message("صارف نہیں ملا۔")
                return

            stored_hash = (
                user.get("PasswordHash")
                or user.get("Password")
                or ""
            )
            if not verify_password(current_password, stored_hash):
                error_message("موجودہ پاس ورڈ درست نہیں ہے۔")
                return


            if len(new_password.strip()) < 8:
                error_message("نیا پاس ورڈ کم از کم 8 حروف پر مشتمل ہونا چاہیے۔")
                return

            if new_password != confirm_password:
                error_message("نیا پاس ورڈ اور تصدیقی پاس ورڈ ایک جیسے نہیں ہیں۔")
                return

            with st.spinner("پاس ورڈ تبدیل کیا جا رہا ہے..."):
                success = sheets.update_user_password(username, new_password.strip())

            if success:
                sheets.add_log(username, "ایڈمن نے اپنا پاس ورڈ تبدیل کیا")
                success_message("آپ کا پاس ورڈ کامیابی سے تبدیل ہو گیا۔")
            else:
                error_message("پاس ورڈ تبدیل کرنے میں خرابی پیش آئی۔")


# ==================================================
# 3) اساتذہ کا انتظام
# ==================================================
def render_teacher_management_section():
    st.subheader("👨‍🏫 اساتذہ کا انتظام")

    sub_tabs = st.tabs(["📋 تمام اساتذہ", "➕ نیا استاد شامل کریں"])

    with sub_tabs[0]:
        render_teachers_list()
    with sub_tabs[1]:
        render_add_teacher_form()


def render_add_teacher_form():
    with st.form("add_teacher_form", clear_on_submit=True):
        username = st.text_input("صارف نام *")
        fullname = st.text_input("پورا نام *")
        password = st.text_input("پاس ورڈ *", type="password")

        submitted = st.form_submit_button("➕ استاد شامل کریں", use_container_width=True)

        if submitted:
            errors = []
            if not is_non_empty(username):
                errors.append("صارف نام لازمی ہے۔")
            elif sheets.get_user(username.strip()) is not None:
                errors.append("یہ صارف نام پہلے سے موجود ہے۔")
            if not is_non_empty(fullname):
                errors.append("پورا نام لازمی ہے۔")
            if not password or len(password.strip()) < 4:
                errors.append("پاس ورڈ کم از کم 4 حروف پر مشتمل ہونا چاہیے۔")

            if errors:
                for e in errors:
                    error_message(e)
                return

            with st.spinner("استاد شامل کیا جا رہا ہے..."):
                success = sheets.add_user(username.strip(), password.strip(), fullname.strip(), config.ROLE_TEACHER)

            if success:
                sheets.add_log(auth.current_username(), f"نیا استاد شامل کیا: {fullname} ({username})")
                success_message(f"استاد '{fullname}' کامیابی سے شامل ہو گیا۔")
                st.rerun()
            else:
                error_message("استاد شامل کرنے میں خرابی پیش آئی۔")


def render_teachers_list():
    users_df = sheets.get_all_users()
    teachers_df = users_df[users_df["Role"] == config.ROLE_TEACHER] if not users_df.empty else users_df

    if teachers_df.empty:
        info_message("ابھی تک کوئی استاد شامل نہیں کیا گیا۔")
        return

    display_df = teachers_df.rename(
        columns={"Username": "صارف نام", "FullName": "پورا نام", "Role": "کردار", "Active": "فعال؟"}
    )[["صارف نام", "پورا نام", "کردار", "فعال؟"]]
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("✏️ استاد میں ترمیم کریں")

    usernames = teachers_df["Username"].tolist()
    selected_username = st.selectbox("استاد منتخب کریں", usernames, key="teacher_select")
    if not selected_username:
        return

    teacher = teachers_df[teachers_df["Username"] == selected_username].iloc[0]
    render_teacher_edit_controls(teacher, selected_username)


def render_teacher_edit_controls(teacher, selected_username):
    is_active = str(teacher.get("Active", "TRUE")).strip().upper() != "FALSE"

    with st.form(f"edit_teacher_form_{selected_username}"):
        new_fullname = st.text_input("پورا نام", value=teacher["FullName"])
        save_name = st.form_submit_button("✅ نام محفوظ کریں", use_container_width=True)
        if save_name:
            if not is_non_empty(new_fullname):
                error_message("نام خالی نہیں ہو سکتا۔")
            else:
                success = sheets.update_user_info(selected_username, fullname=new_fullname.strip())
                if success:
                    sheets.add_log(auth.current_username(), f"استاد کا نام تبدیل کیا: {selected_username}")
                    success_message("نام کامیابی سے اپ ڈیٹ ہو گیا۔")
                    st.rerun()
                else:
                    error_message("نام اپ ڈیٹ کرنے میں خرابی پیش آئی۔")

    col1, col2, col3 = st.columns(3)

    with col1:
        toggle_label = "🚫 غیر فعال کریں" if is_active else "✅ فعال کریں"
        if st.button(toggle_label, key=f"toggle_{selected_username}", use_container_width=True):
            success = sheets.update_user_info(selected_username, active=not is_active)
            if success:
                status_text = "غیر فعال" if is_active else "فعال"
                sheets.add_log(
                    auth.current_username(), f"استاد کی حیثیت تبدیل کی: {selected_username} کو {status_text} کر دیا"
                )
                success_message(f"استاد کی حیثیت '{status_text}' میں تبدیل ہو گئی۔")
                st.rerun()
            else:
                error_message("حیثیت تبدیل کرنے میں خرابی پیش آئی۔")

    with col2:
        if st.button("🔑 پاس ورڈ ری سیٹ کریں", key=f"reset_pw_btn_{selected_username}", use_container_width=True):
            st.session_state[f"show_reset_{selected_username}"] = True

    with col3:
        if st.button("🗑️ استاد حذف کریں", key=f"delete_btn_{selected_username}", use_container_width=True):
            st.session_state["confirm_delete_teacher"] = selected_username

    if st.session_state.get(f"show_reset_{selected_username}"):
        with st.form(f"reset_password_form_{selected_username}"):
            new_password = st.text_input("نیا پاس ورڈ", type="password")
            confirm_reset = st.form_submit_button("✅ پاس ورڈ ری سیٹ کریں", use_container_width=True)
            if confirm_reset:
                if not new_password or len(new_password.strip()) < 4:
                    error_message("پاس ورڈ کم از کم 4 حروف پر مشتمل ہونا چاہیے۔")
                else:
                    success = sheets.update_user_password(selected_username, new_password.strip())
                    if success:
                        sheets.add_log(
                            auth.current_username(), f"استاد کا پاس ورڈ ری سیٹ کیا: {selected_username}"
                        )
                        success_message("پاس ورڈ کامیابی سے ری سیٹ ہو گیا۔")
                        del st.session_state[f"show_reset_{selected_username}"]
                        st.rerun()
                    else:
                        error_message("پاس ورڈ ری سیٹ کرنے میں خرابی پیش آئی۔")

    if st.session_state.get("confirm_delete_teacher") == selected_username:
        warning_message(f"کیا آپ واقعی استاد '{teacher['FullName']}' ({selected_username}) کو حذف کرنا چاہتے ہیں؟")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ ہاں، حذف کریں", key=f"confirm_del_yes_{selected_username}", use_container_width=True):
                success = sheets.delete_user(selected_username)
                if success:
                    sheets.add_log(auth.current_username(), f"استاد حذف کیا: {selected_username}")
                    del st.session_state["confirm_delete_teacher"]
                    success_message("استاد کامیابی سے حذف کر دیا گیا۔")
                    st.rerun()
                else:
                    error_message("استاد حذف کرنے میں خرابی پیش آئی۔")
        with c2:
            if st.button("❌ منسوخ کریں", key=f"confirm_del_no_{selected_username}", use_container_width=True):
                del st.session_state["confirm_delete_teacher"]
                st.rerun()


# ==================================================
# 4) تھیم کی ترتیبات
# ==================================================
def render_theme_settings_section():
    st.subheader("🎨 تھیم کی ترتیبات")
    info_message(
        "یہاں محفوظ کیے گئے رنگ ریکارڈ کے لیے محفوظ ہوتے ہیں۔ فی الحال بنیادی تھیم "
        "config.py سے لاگو ہوتی ہے — مستقبل میں ان ترتیبات کو خودکار طور پر لاگو کرنے کی "
        "سہولت شامل کی جا سکتی ہے۔"
    )

    current_primary = sheets.get_setting("PrimaryColor", config.COLOR_PRIMARY)
    current_accent = sheets.get_setting("AccentColor", config.COLOR_ACCENT)

    with st.form("theme_settings_form"):
        col1, col2 = st.columns(2)
        with col1:
            primary_color = st.color_picker("بنیادی رنگ (Primary Color)", value=current_primary)
        with col2:
            accent_color = st.color_picker("نمایاں رنگ (Accent Color)", value=current_accent)

        submitted = st.form_submit_button("✅ تھیم محفوظ کریں", use_container_width=True)

        if submitted:
            ok1 = sheets.set_setting("PrimaryColor", primary_color)
            ok2 = sheets.set_setting("AccentColor", accent_color)
            if ok1 and ok2:
                sheets.add_log(auth.current_username(), "تھیم کے رنگ تبدیل کیے")
                success_message("تھیم کی ترتیبات محفوظ ہو گئیں۔")
            else:
                error_message("تھیم محفوظ کرنے میں خرابی پیش آئی۔")


# ==================================================
# 5) سسٹم کی معلومات
# ==================================================
def render_system_info_section():
    st.subheader("📊 سسٹم کی معلومات")

    with st.spinner("معلومات لوڈ ہو رہی ہیں..."):
        students_df = sheets.get_all_students()
        users_df = sheets.get_all_users()
        attendance_df = sheets.get_all_attendance()
        logs_df = sheets.get_all_logs()

    total_students = len(students_df)
    total_teachers = len(users_df[users_df["Role"] == config.ROLE_TEACHER]) if not users_df.empty else 0
    total_attendance = len(attendance_df)
    total_logs = len(logs_df)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_stat_card("کل طلباء", total_students, "🎓")
    with col2:
        render_stat_card("کل اساتذہ", total_teachers, "👨‍🏫")
    with col3:
        render_stat_card("کل حاضری ریکارڈز", total_attendance, "📋")
    with col4:
        render_stat_card("کل لاگ اندراجات", total_logs, "🧾")


# ==================================================
# 6) بیک اپ کی معلومات
# ==================================================
def render_backup_info_section():
    st.subheader("💾 بیک اپ کی معلومات")

    st.markdown(f"**📄 گوگل شیٹ کا نام:** {config.GOOGLE_SHEET_NAME}")

    connected_account = "معلوم نہیں"
    try:
        client = sheets.get_client()
        connected_account = getattr(client.auth, "service_account_email", "معلوم نہیں")
    except Exception:
        pass
    st.markdown(f"**🔐 منسلک اکاؤنٹ:** {connected_account}")

    last_backup = sheets.get_setting("LastBackupDate", None)
    if last_backup:
        st.markdown(f"**🕒 آخری بیک اپ کی تاریخ:** {last_backup}")
    else:
        st.markdown("**🕒 آخری بیک اپ کی تاریخ:** دستیاب نہیں")

    st.markdown("---")
    if st.button("📌 آج کی تاریخ کو بطور آخری بیک اپ محفوظ کریں", use_container_width=True):
        timestamp = f"{today_str()} {now_time_str()}"
        success = sheets.set_setting("LastBackupDate", timestamp)
        if success:
            sheets.add_log(auth.current_username(), "بیک اپ کی تاریخ اپ ڈیٹ کی")
            success_message("بیک اپ کی تاریخ محفوظ ہو گئی۔")
            st.rerun()
        else:
            error_message("بیک اپ کی تاریخ محفوظ کرنے میں خرابی پیش آئی۔")

    info_message(
        "گوگل شیٹس خود بخود گوگل ڈرائیو پر محفوظ رہتی ہیں۔ مکمل بیک اپ کے لیے، اپنی "
        "گوگل شیٹ کو گوگل ڈرائیو کے 'File > Make a copy' آپشن سے کاپی کریں۔"
    )