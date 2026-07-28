# students.py
"""
طلباء کا انتظام (Student Management)
==================================================
یہ صفحہ صرف منتظم (Admin) استعمال کر سکتا ہے۔
یہاں سے طلباء کا اندراج، ترمیم، حذف، فعال/غیر فعال کرنا، تلاش، رپورٹ ایکسپورٹ
اور اعداد و شمار دیکھے جا سکتے ہیں۔

اصول: اس فائل میں گوگل شیٹس کا کوئی براہِ راست لاجک نہیں لکھا گیا — ہر ڈیٹا بیس
عملیہ sheets.py کے ذریعے انجام دیا جاتا ہے۔
"""

import streamlit as st
import pandas as pd

import config
import sheets
import auth
from utils import (
    require_admin,
    render_stat_card,
    success_message,
    error_message,
    is_valid_phone,
    is_non_empty,
)
from reports import to_excel_bytes, dataframe_to_pdf_bytes


# صرف اسکرین پر دکھانے کے لیے استاد کے اردو نام۔
# Google Sheet اور login username تبدیل نہیں ہوں گے۔
TEACHER_DISPLAY_NAMES = {
    "amir": "قاری عامر",
    "ifrahim": "قاری افراہیم",
    "anas": "قاری انس",
    "khuzaima": "قاری خزیمہ",
}


def get_teacher_display_name(username):
    """استاد کا username محفوظ رکھتے ہوئے صرف UI میں اردو نام دکھائیں۔"""
    username_text = str(username or "").strip()
    return TEACHER_DISPLAY_NAMES.get(username_text.lower(), username_text)


# اردو کالم ناموں کی مینوی (پوری فائل میں دوبارہ استعمال ہوتی ہے)
COLUMN_LABELS = {
    "StudentName": "طالب علم کا نام",
    "FatherName": "والد کا نام",
    "AssignedTeacher": "متعلقہ استاد",
    "Age": "عمر",
    "PhoneNumber": "فون نمبر",
    "Address": "پتہ",
    "AdmissionDate": "داخلہ کی تاریخ",
    "Status": "حیثیت",
}

def render_students_page():
    # ==================================================
    # 1) رسائی کنٹرول — صرف منتظم
    # ==================================================
    require_admin()

    st.markdown("""
<div class="page-header">
    <div class="page-title">🎓 طلباء کا انتظام</div>
    <div class="page-subtitle">
        یہاں سے طلباء کا اندراج، ترمیم، حذف اور تلاش کی جا سکتی ہے۔
    </div>
</div>
""", unsafe_allow_html=True)
    # ==================================================
    # 2) ڈیش بورڈ کارڈز (کل / فعال / غیر فعال طلباء)
    # ==================================================
    render_summary_cards()

    st.markdown("---")

    tabs = st.tabs(
        ["📋 تمام طلباء", "🔍 تلاش کریں", "➕ نیا طالب علم شامل کریں", "📊 اعداد و شمار"]
    )

    with tabs[0]:
        render_students_list()
    with tabs[1]:
        render_search_students()
    with tabs[2]:
        render_add_student_form()
    with tabs[3]:
        render_statistics()


# ==================================================
# ڈیش بورڈ کارڈز
# ==================================================
def render_summary_cards():
    df = sheets.get_all_students()
    total = len(df)
    active = len(df[df["Status"] == config.STUDENT_STATUS_ACTIVE]) if not df.empty else 0
    inactive = len(df[df["Status"] == config.STUDENT_STATUS_INACTIVE]) if not df.empty else 0

    col1, col2, col3 = st.columns(3)
    with col1:
        render_stat_card("کل طلباء", total, "🎓")
    with col2:
        render_stat_card("فعال طلباء", active, "✅")
    with col3:
        render_stat_card("غیر فعال طلباء", inactive, "🚫")


# ==================================================
# نیا طالب علم شامل کریں (Add)
# ==================================================
def render_add_student_form():
    st.subheader("➕ نیا طالب علم شامل کریں")

    # config.py میں موجود صرف اساتذہ کی فہرست
    teachers = [
        user
        for user in config.DEFAULT_USERS
        if user.get("Role") == config.ROLE_TEACHER
    ]

    teacher_usernames = [
        teacher["Username"]
        for teacher in teachers
    ]

    teacher_names = {
        teacher["Username"]: get_teacher_display_name(teacher["Username"])
        for teacher in teachers
    }

    with st.form("add_student_form", clear_on_submit=True):

        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input("طالب علم کا نام *")

            father_name = st.text_input("والد کا نام *")

            assigned_teacher = st.selectbox(
                "متعلقہ استاد *",
                options=teacher_usernames,
                format_func=lambda username: teacher_names.get(
                    username,
                    username,
                ),
            )

            age = st.number_input(
                "عمر (اختیاری)",
                min_value=3,
                max_value=100,
                step=1,
                value=10,
            )

        with col2:
            phone = st.text_input("فون نمبر (اختیاری)")

            address = st.text_area("پتہ (اختیاری)")

            admission_date = st.date_input(
                "داخلہ کی تاریخ (اختیاری)"
            )

        submitted = st.form_submit_button(
            "طالب علم شامل کریں",
            use_container_width=True,
        )

        if submitted:

            errors = validate_student_input(
                name,
                father_name,
                assigned_teacher,
                phone,
            )

            if errors:
                for error in errors:
                    error_message(error)
                return

            with st.spinner(
                "طالب علم شامل کیا جا رہا ہے..."
            ):
                success = sheets.add_student(
                    name.strip(),
                    father_name.strip(),
                    assigned_teacher,
                    age,
                    phone.strip(),
                    address.strip(),
                    str(admission_date),
                )

            if success:

                assigned_teacher_name = teacher_names.get(
                    assigned_teacher,
                    assigned_teacher,
                )

                sheets.add_log(
                    auth.current_username(),
                    (
                        f"نیا طالب علم شامل کیا: {name}، "
                        f"متعلقہ استاد: {assigned_teacher_name}"
                    ),
                )

                success_message(
                    f"طالب علم '{name}' کامیابی سے شامل ہو گیا۔"
                )

                st.rerun()

            else:
                error_message(
                    "طالب علم شامل کرنے میں خرابی پیش آئی۔ "
                    "دوبارہ کوشش کریں۔"
                )


def validate_student_input(
    name,
    father_name,
    assigned_teacher,
    phone,
):
    """
    طالب علم کے فارم کی تصدیق کریں۔
    نام، والد کا نام اور متعلقہ استاد لازمی ہیں۔
    """

    errors = []

    if not is_non_empty(name):
        errors.append("طالب علم کا نام لازمی ہے۔")

    if not is_non_empty(father_name):
        errors.append("والد کا نام لازمی ہے۔")

    if not assigned_teacher:
        errors.append("متعلقہ استاد منتخب کرنا لازمی ہے۔")

    if phone and phone.strip() and not is_valid_phone(phone):
        errors.append("فون نمبر درست نہیں ہے۔")

    return errors

# ==================================================
# تمام طلباء کی فہرست + ترمیم / حذف / حیثیت تبدیل کریں
# ==================================================
def render_students_list():
    st.subheader("📋 تمام طلباء")

    df = sheets.get_all_students()

    if df.empty:
        st.info("ℹ️ ابھی تک کوئی طالب علم شامل نہیں کیا گیا۔")
        return

    status_filter = st.selectbox(
        "حیثیت کے مطابق فلٹر کریں",
        ["تمام"] + config.STUDENT_STATUSES,
        key="list_status_filter",
    )

    if status_filter == "تمام":
        filtered_df = df
    else:
        filtered_df = df[
            df["Status"].astype(str) == str(status_filter)
        ]

    display_table(filtered_df)
    render_export_buttons(filtered_df, "students_list")

    st.markdown("---")
    st.subheader("✏️ ترمیم / حذف / حیثیت تبدیل کریں")

    student_indexes = df.index.tolist()

    selected_index = st.selectbox(
        "طالب علم منتخب کریں",
        options=student_indexes,
        format_func=lambda index: (
            f"{df.loc[index, 'StudentName']} — "
            f"{df.loc[index, 'FatherName']} — "
            f"{get_teacher_display_name(df.loc[index, 'AssignedTeacher'])}"
        ),
        key="edit_select_student",
    )

    if selected_index is None:
        return

    student = df.loc[selected_index]

    original_name = str(
        student.get("StudentName", "")
    ).strip()

    original_father_name = str(
        student.get("FatherName", "")
    ).strip()

    original_assigned_teacher = str(
        student.get("AssignedTeacher", "")
    ).strip()

    render_edit_form(
        student,
        original_name,
        original_father_name,
        original_assigned_teacher,
    )

    render_status_toggle(
        student,
        original_name,
        original_father_name,
        original_assigned_teacher,
    )

    render_delete_section(
        student,
        original_name,
        original_father_name,
        original_assigned_teacher,
    )


def display_table(df: pd.DataFrame):
    """
    طلباء کا جدول اردو کالم ناموں کے ساتھ دکھائیں۔
    """

    display_df = df.copy()

    if "AssignedTeacher" in display_df.columns:
        display_df["AssignedTeacher"] = display_df["AssignedTeacher"].apply(
            get_teacher_display_name
        )

    display_df = display_df.rename(columns=COLUMN_LABELS)

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(f"کل نتائج: {len(df)}")


def render_edit_form(
    student,
    original_name,
    original_father_name,
    original_assigned_teacher,
):
    teachers = [
        user
        for user in config.DEFAULT_USERS
        if user.get("Role") == config.ROLE_TEACHER
    ]

    teacher_usernames = [
        str(teacher.get("Username", "")).strip()
        for teacher in teachers
        if str(teacher.get("Username", "")).strip()
    ]

    teacher_names = {
        str(teacher.get("Username", "")).strip():
        get_teacher_display_name(teacher.get("Username", ""))
        for teacher in teachers
    }

    if (
        original_assigned_teacher
        and original_assigned_teacher not in teacher_usernames
    ):
        teacher_usernames.append(original_assigned_teacher)

    teacher_index = 0

    if original_assigned_teacher in teacher_usernames:
        teacher_index = teacher_usernames.index(
            original_assigned_teacher
        )

    age_text = str(
        student.get("Age", "")
    ).strip()

    try:
        age_value = int(float(age_text))
    except (ValueError, TypeError):
        age_value = 10

    age_value = max(3, min(age_value, 100))

    current_status = str(
        student.get(
            "Status",
            config.STUDENT_STATUS_ACTIVE,
        )
    ).strip()

    if current_status in config.STUDENT_STATUSES:
        status_index = config.STUDENT_STATUSES.index(
            current_status
        )
    else:
        status_index = 0

    with st.form("edit_student_form"):
        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input(
                "طالب علم کا نام *",
                value=str(
                    student.get("StudentName", "")
                ),
            )

            father_name = st.text_input(
                "والد کا نام *",
                value=str(
                    student.get("FatherName", "")
                ),
            )

            assigned_teacher = st.selectbox(
                "متعلقہ استاد *",
                options=teacher_usernames,
                index=teacher_index,
                format_func=lambda username: teacher_names.get(
                    username,
                    username,
                ),
            )

            age = st.number_input(
                "عمر",
                min_value=3,
                max_value=100,
                step=1,
                value=age_value,
            )

        with col2:
            phone = st.text_input(
                "فون نمبر",
                value=str(
                    student.get("PhoneNumber", "")
                ),
            )

            address = st.text_area(
                "پتہ",
                value=str(
                    student.get("Address", "")
                ),
            )

            status = st.selectbox(
                "حیثیت",
                options=config.STUDENT_STATUSES,
                index=status_index,
            )

        update_clicked = st.form_submit_button(
            "✅ تبدیلیاں محفوظ کریں",
            use_container_width=True,
        )

        if update_clicked:
            errors = validate_student_input(
                name,
                father_name,
                assigned_teacher,
                phone,
            )

            if errors:
                for error in errors:
                    error_message(error)
                return

            admission_date = str(
                student.get("AdmissionDate", "")
            ).strip()

            with st.spinner(
                "تبدیلیاں محفوظ کی جا رہی ہیں..."
            ):
                success = sheets.update_student(
                    original_name,
                    original_father_name,
                    original_assigned_teacher,
                    name.strip(),
                    father_name.strip(),
                    assigned_teacher,
                    age,
                    phone.strip(),
                    address.strip(),
                    admission_date,
                    status,
                )

            if success:
                sheets.add_log(
                    auth.current_username(),
                    (
                        "طالب علم کی معلومات میں ترمیم کی: "
                        f"{original_name} ولد "
                        f"{original_father_name}"
                    ),
                )

                success_message(
                    "طالب علم کی معلومات کامیابی سے "
                    "اپ ڈیٹ ہو گئیں۔"
                )

                st.rerun()

            else:
                error_message(
                    "معلومات اپ ڈیٹ کرنے میں خرابی پیش آئی۔"
                )


def render_status_toggle(
    student,
    student_name,
    father_name,
    assigned_teacher,
):
    """
    طالب علم کو ایک کلک میں فعال یا غیر فعال کریں۔
    """

    current_status = str(
        student.get(
            "Status",
            config.STUDENT_STATUS_ACTIVE,
        )
    ).strip()

    if current_status == config.STUDENT_STATUS_ACTIVE:
        new_status = config.STUDENT_STATUS_INACTIVE
        button_label = "🚫 اس طالب علم کو غیر فعال کریں"
    else:
        new_status = config.STUDENT_STATUS_ACTIVE
        button_label = "✅ اس طالب علم کو فعال کریں"

    unique_key = (
        f"{student_name}_"
        f"{father_name}_"
        f"{assigned_teacher}"
    )

    if st.button(
        button_label,
        key=f"toggle_status_{unique_key}",
        use_container_width=True,
    ):
        with st.spinner(
            "حیثیت تبدیل کی جا رہی ہے..."
        ):
            success = sheets.update_student_status(
                student_name,
                father_name,
                assigned_teacher,
                new_status,
            )

        if success:
            sheets.add_log(
                auth.current_username(),
                (
                    "طالب علم کی حیثیت تبدیل کی: "
                    f"{student_name} کو {new_status} کر دیا"
                ),
            )

            success_message(
                f"طالب علم کی حیثیت '{new_status}' "
                "میں تبدیل ہو گئی۔"
            )

            st.rerun()

        else:
            error_message(
                "حیثیت تبدیل کرنے میں خرابی پیش آئی۔"
            )


def render_delete_section(
    student,
    student_name,
    father_name,
    assigned_teacher,
):
    """
    طالب علم کو حذف کرنے سے پہلے تصدیق حاصل کریں۔
    """

    confirm_key = "confirm_delete_student"

    unique_key = (
        f"{student_name}_"
        f"{father_name}_"
        f"{assigned_teacher}"
    )

    if st.button(
        "🗑️ طالب علم حذف کریں",
        key=f"delete_btn_{unique_key}",
        use_container_width=True,
    ):
        st.session_state[confirm_key] = unique_key

    if st.session_state.get(confirm_key) != unique_key:
        return

    st.warning(
        f"⚠️ کیا آپ واقعی '{student_name}' "
        f"ولد '{father_name}' کو حذف کرنا چاہتے ہیں؟ "
        "یہ عمل واپس نہیں ہو سکتا۔"
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "✅ ہاں، حذف کریں",
            key=f"confirm_yes_{unique_key}",
            use_container_width=True,
        ):
            with st.spinner(
                "طالب علم حذف کیا جا رہا ہے..."
            ):
                success = sheets.delete_student(
                    student_name,
                    father_name,
                    assigned_teacher,
                )

            if success:
                sheets.add_log(
                    auth.current_username(),
                    (
                        "طالب علم حذف کیا: "
                        f"{student_name} ولد "
                        f"{father_name}"
                    ),
                )

                st.session_state.pop(
                    confirm_key,
                    None,
                )

                success_message(
                    "طالب علم کامیابی سے حذف کر دیا گیا۔"
                )

                st.rerun()

            else:
                error_message(
                    "طالب علم حذف کرنے میں خرابی پیش آئی۔"
                )

    with col2:
        if st.button(
            "❌ منسوخ کریں",
            key=f"confirm_no_{unique_key}",
            use_container_width=True,
        ):
            st.session_state.pop(
                confirm_key,
                None,
            )

            st.rerun()

# ==================================================
# تلاش (فوری فلٹرنگ)
# ==================================================
def render_search_students():
    st.subheader("🔍 طلباء تلاش کریں")

    df = sheets.get_all_students()
    if df.empty:
        st.info("ℹ️ ابھی تک کوئی طالب علم شامل نہیں کیا گیا۔")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        name_query = st.text_input("طالب علم کا نام", key="search_name")
    with col2:
        father_query = st.text_input("والد کا نام", key="search_father")
    with col3:
        phone_query = st.text_input("فون نمبر", key="search_phone")

    result = df.copy()

    if name_query.strip():
        result = result[result["StudentName"].astype(str).str.contains(name_query.strip(), case=False, na=False)]
    if father_query.strip():
        result = result[result["FatherName"].astype(str).str.contains(father_query.strip(), case=False, na=False)]
    if phone_query.strip():
        result = result[result["PhoneNumber"].astype(str).str.contains(phone_query.strip(), case=False, na=False)]

    if not (name_query.strip() or father_query.strip() or phone_query.strip()):
        st.info("ℹ️ تلاش کرنے کے لیے اوپر کسی بھی خانے میں کچھ لکھیں۔")
        return

    if result.empty:
        st.info("ℹ️ کوئی نتیجہ نہیں ملا۔")
    else:
        display_table(result)
        render_export_buttons(result, "search_results")


# ==================================================
# ایکسپورٹ بٹن (Excel / PDF)
# ==================================================
def render_export_buttons(df: pd.DataFrame, filename_prefix: str):
    if df.empty:
        return

    display_df = df.copy()

    if "AssignedTeacher" in display_df.columns:
        display_df["AssignedTeacher"] = display_df["AssignedTeacher"].apply(
            get_teacher_display_name
        )

    display_df = display_df.rename(columns=COLUMN_LABELS)

    col1, col2 = st.columns(2)
    with col1:
        excel_data = to_excel_bytes(display_df, sheet_name="Students")
        st.download_button(
            "⬇️ Excel میں ایکسپورٹ کریں",
            data=excel_data,
            file_name=f"{filename_prefix}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key=f"excel_{filename_prefix}",
        )
    with col2:
        pdf_data = dataframe_to_pdf_bytes(display_df, "Students List", "Madarsa Attendance Portal")
        st.download_button(
            "⬇️ PDF میں ایکسپورٹ کریں",
            data=pdf_data,
            file_name=f"{filename_prefix}.pdf",
            mime="application/pdf",
            use_container_width=True,
            key=f"pdf_{filename_prefix}",
        )


# ==================================================
# اعداد و شمار (Statistics)
# ==================================================
def render_statistics():
    st.subheader("📊 اعداد و شمار")

    df = sheets.get_all_students()
    if df.empty:
        st.info("ℹ️ ابھی تک کوئی طالب علم شامل نہیں کیا گیا۔")
        return

    total = len(df)
    active = len(df[df["Status"] == config.STUDENT_STATUS_ACTIVE])
    inactive = len(df[df["Status"] == config.STUDENT_STATUS_INACTIVE])

    col1, col2, col3 = st.columns(3)
    with col1:
        render_stat_card("کل طلباء", total, "🎓")
    with col2:
        render_stat_card("فعال طلباء", active, "✅")
    with col3:
        render_stat_card("غیر فعال طلباء", inactive, "🚫")

    st.markdown("### 🆕 حال ہی میں شامل کیے گئے طلباء")
    recent_students = df.tail(5).iloc[::-1]
    display_table(recent_students)
