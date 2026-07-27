# attendance.py
"""
حاضری اور روزانہ تعلیمی کام کا مکمل انتظام۔

اہم اصول:
- طالب علم کی شناخت StudentName + FatherName + AssignedTeacher سے ہوتی ہے۔
- صبح اور دوپہر کی حاضری الگ الگ محفوظ ہوتی ہے۔
- استاد صرف اپنے فعال طلباء کا ریکارڈ درج کر سکتا ہے۔
- استاد صرف آج کے اپنے ریکارڈ میں ترمیم کر سکتا ہے؛ حذف نہیں کر سکتا۔
- منتظم تمام اساتذہ کی طرف سے اندراج، ترمیم اور حذف کر سکتا ہے۔
- سبق، سبقی، منزل اور پاؤ کا روزانہ ریکارڈ بھی اسی صفحے سے درج ہوتا ہے۔
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import auth
import config
import sheets
from utils import (
    error_message,
    info_message,
    render_stat_card,
    require_login,
    success_message,
    today_str,
    warning_message,
)


ATTENDANCE_COLUMN_LABELS = {
    "Date": "تاریخ",
    "AttendanceSession": "حاضری کا وقت",
    "StudentName": "طالب علم کا نام",
    "FatherName": "والد کا نام",
    "TeacherUsername": "استاد کا یوزرنیم",
    "TeacherName": "استاد",
    "Status": "حیثیت",
    "TimeSubmitted": "اندراج کا وقت",
}

DAILY_WORK_COLUMN_LABELS = {
    "Date": "تاریخ",
    "StudentName": "طالب علم کا نام",
    "FatherName": "والد کا نام",
    "TeacherUsername": "استاد کا یوزرنیم",
    "TeacherName": "استاد",
    "SabaqSurah": "سبق: سورت",
    "SabaqAyah": "سبق: آیت",
    "SabqiSurah": "سبقی: سورت",
    "SabqiAyah": "سبقی: آیت",
    "ManzilJuz": "منزل: پارہ",
    "ManzilAmount": "منزل: مقدار",
    "ManzilHalf": "منزل: نصف",
    "PaoJuz": "پاؤ: پارہ",
    "PaoQuarter": "پاؤ نمبر",
    "TimeSubmitted": "اندراج کا وقت",
}


def _clean(value) -> str:
    return str(value if value is not None else "").strip()


def _normalise(value) -> str:
    return _clean(value).casefold()


def _student_key(student_name, father_name) -> str:
    return f"{_normalise(student_name)}|||{_normalise(father_name)}"


def _teacher_key(username: str) -> str:
    return _normalise(username)


def _get_teacher_records() -> list[dict]:
    users_df = sheets.get_all_users()
    if users_df.empty:
        return []

    required = {"Username", "FullName", "Role"}
    if not required.issubset(users_df.columns):
        return []

    teachers = users_df[
        users_df["Role"].astype(str).str.strip() == config.ROLE_TEACHER
    ].copy()

    if "Active" in teachers.columns:
        active = teachers["Active"].astype(str).str.strip().str.lower()
        teachers = teachers[active.isin(["true", "1", "yes", "فعال"])]

    result = []
    for _, row in teachers.iterrows():
        username = _clean(row.get("Username"))
        full_name = _clean(row.get("FullName")) or username
        if username:
            result.append({"Username": username, "FullName": full_name})
    return result


def _filter_students_for_teacher(
    students_df: pd.DataFrame,
    teacher_username: str,
) -> pd.DataFrame:
    if students_df.empty:
        return students_df

    required = {"StudentName", "FatherName", "AssignedTeacher", "Status"}
    if not required.issubset(students_df.columns):
        missing = required - set(students_df.columns)
        error_message(
            "طلباء کی شیٹ میں مطلوبہ کالم موجود نہیں: "
            + "، ".join(sorted(missing))
        )
        return pd.DataFrame()

    assigned = students_df["AssignedTeacher"].astype(str).map(_normalise)
    status = students_df["Status"].astype(str).str.strip()

    return students_df[
        (assigned == _teacher_key(teacher_username))
        & (status == config.STUDENT_STATUS_ACTIVE)
    ].copy()


def _active_students_for_teacher(teacher_username: str) -> pd.DataFrame:
    return _filter_students_for_teacher(
        sheets.get_active_students(), teacher_username
    )


def _is_friday(date_value) -> bool:
    return pd.Timestamp(date_value).weekday() == config.FRIDAY_WEEKDAY


# ==================================================
# استاد کا مرکزی صفحہ
# ==================================================
def render_mark_attendance_page():
    require_login()

    if not auth.is_teacher():
        error_message("یہ صفحہ صرف اساتذہ کے لیے مخصوص ہے۔")
        st.stop()

    teacher_username = auth.current_username()
    teacher_name = auth.current_fullname()

    st.title("📝 حاضری اور روزانہ تعلیمی کام")
    st.caption(f"استاد: {teacher_name}")

    tabs = st.tabs(
        [
            "✅ حاضری درج کریں",
            "📖 تعلیمی کام درج کریں",
            "✏️ آج کے ریکارڈ میں ترمیم",
        ]
    )

    with tabs[0]:
        render_marking_form(teacher_username, teacher_name)

    with tabs[1]:
        render_daily_work_form(teacher_username, teacher_name)

    with tabs[2]:
        edit_tabs = st.tabs(["حاضری", "تعلیمی کام"])
        with edit_tabs[0]:
            render_teacher_edit_section(teacher_username, teacher_name)
        with edit_tabs[1]:
            render_teacher_daily_work_edit_section(
                teacher_username, teacher_name
            )


# ==================================================
# حاضری درج کرنا
# ==================================================
def render_marking_form(
    teacher_username: str,
    teacher_name: str,
):
    teacher_username = _clean(teacher_username)
    teacher_name = _clean(teacher_name)

    col1, col2 = st.columns(2)
    with col1:
        selected_date = st.date_input(
            "📅 تاریخ منتخب کریں",
            value=pd.to_datetime(today_str()),
            key=f"mark_date_{teacher_username}",
        )
    with col2:
        attendance_session = st.selectbox(
            "🕒 حاضری کا وقت منتخب کریں",
            config.ATTENDANCE_SESSIONS,
            key=f"mark_session_{teacher_username}",
        )

    date_str = str(selected_date)

    if _is_friday(selected_date):
        warning_message(
            "جمعہ تعلیمی چھٹی ہے۔ ضرورت کی صورت میں ہی ریکارڈ درج کریں۔"
        )

    active_students = _active_students_for_teacher(teacher_username)
    if active_students.empty:
        info_message(f"{teacher_name} کے ساتھ کوئی فعال طالب علم مقرر نہیں ہے۔")
        return

    attendance_df = sheets.get_all_attendance()
    already_marked = set()

    if not attendance_df.empty:
        required = {"Date", "AttendanceSession", "StudentName", "FatherName"}
        if not required.issubset(attendance_df.columns):
            missing = required - set(attendance_df.columns)
            error_message(
                "حاضری کی شیٹ میں مطلوبہ کالم موجود نہیں: "
                + "، ".join(sorted(missing))
            )
            return

        existing = attendance_df[
            (attendance_df["Date"].astype(str).str.strip() == date_str)
            & (
                attendance_df["AttendanceSession"].astype(str).str.strip()
                == attendance_session
            )
        ]
        already_marked = {
            _student_key(row.get("StudentName"), row.get("FatherName"))
            for _, row in existing.iterrows()
        }

    active_students = active_students.copy()
    active_students["_StudentKey"] = active_students.apply(
        lambda row: _student_key(
            row.get("StudentName"), row.get("FatherName")
        ),
        axis=1,
    )
    pending = active_students[
        ~active_students["_StudentKey"].isin(already_marked)
    ].copy()

    if pending.empty:
        warning_message(
            f"{date_str} کی {attendance_session} تمام طلباء کے لیے پہلے ہی درج ہے۔"
        )
        return

    marked_count = len(active_students) - len(pending)
    if marked_count:
        info_message(
            f"{marked_count} طلباء کی {attendance_session} پہلے سے درج ہے۔ "
            "صرف باقی طلباء دکھائے جا رہے ہیں۔"
        )

    form_key = (
        f"attendance_form_{teacher_username}_{date_str}_{attendance_session}"
    )

    with st.form(form_key):
        st.markdown(
            f"#### 👥 {teacher_name} کے طلباء — {attendance_session}"
        )
        statuses = {}

        for index, (_, student) in enumerate(pending.iterrows()):
            student_name = _clean(student.get("StudentName"))
            father_name = _clean(student.get("FatherName"))
            key = _student_key(student_name, father_name)

            c1, c2 = st.columns([3, 4])
            with c1:
                st.markdown(f"**{student_name}**  \nوالد: {father_name}")
            with c2:
                statuses[key] = st.radio(
                    "حیثیت",
                    config.ATTENDANCE_STATUSES,
                    horizontal=True,
                    index=0,
                    key=f"{form_key}_{index}",
                    label_visibility="collapsed",
                )
            st.divider()

        submitted = st.form_submit_button(
            "✅ حاضری جمع کروائیں", use_container_width=True
        )

    if not submitted:
        return

    records = []
    for _, student in pending.iterrows():
        student_name = _clean(student.get("StudentName"))
        father_name = _clean(student.get("FatherName"))
        records.append(
            {
                "StudentName": student_name,
                "FatherName": father_name,
                "Status": statuses[_student_key(student_name, father_name)],
            }
        )

    with st.spinner("حاضری محفوظ کی جا رہی ہے..."):
        success = sheets.submit_attendance(
            date_str,
            teacher_username,
            teacher_name,
            records,
            attendance_session,
        )

    if success:
        sheets.add_log(
            auth.current_username(),
            f"{attendance_session} جمع کروائی: {date_str} برائے "
            f"{teacher_name} ({len(records)} طلباء)",
        )
        success_message("حاضری کامیابی سے محفوظ ہو گئی۔")
        st.rerun()
    else:
        error_message("حاضری محفوظ کرنے میں خرابی پیش آئی۔")


# ==================================================
# روزانہ تعلیمی کام درج کرنا
# ==================================================
def render_daily_work_form(
    teacher_username: str,
    teacher_name: str,
):
    """
    ایک وقت میں صرف ایک طالب علم کا تعلیمی کام درج کریں۔

    استاد جس طالب علم کا سبق، سبقی، منزل یا پاؤ سن لے،
    اسی وقت اسی طالب علم کا ریکارڈ محفوظ کر سکتا ہے۔
    """
    teacher_username = _clean(teacher_username)
    teacher_name = _clean(teacher_name)

    selected_date = st.date_input(
        "📅 تعلیمی کام کی تاریخ",
        value=pd.to_datetime(today_str()),
        key=f"work_date_{teacher_username}",
    )
    date_str = str(selected_date)

    if _is_friday(selected_date):
        warning_message(
            "جمعہ تعلیمی چھٹی ہے۔ ضرورت کی صورت میں ہی ریکارڈ درج کریں۔"
        )

    students = _active_students_for_teacher(teacher_username)
    if students.empty:
        info_message(f"{teacher_name} کے ساتھ کوئی فعال طالب علم مقرر نہیں ہے۔")
        return

    work_df = sheets.get_all_daily_work()
    existing_keys = set()

    if not work_df.empty and {
        "Date", "StudentName", "FatherName"
    }.issubset(work_df.columns):
        existing = work_df[
            work_df["Date"].astype(str).str.strip() == date_str
        ]
        existing_keys = {
            _student_key(row.get("StudentName"), row.get("FatherName"))
            for _, row in existing.iterrows()
        }

    students = students.copy()
    students["_StudentKey"] = students.apply(
        lambda row: _student_key(
            row.get("StudentName"), row.get("FatherName")
        ),
        axis=1,
    )

    pending = students[
        ~students["_StudentKey"].isin(existing_keys)
    ].copy()

    if pending.empty:
        success_message(
            f"✅ {date_str} کا تعلیمی کام تمام طلباء کے لیے درج ہو چکا ہے۔"
        )
        return

    completed_count = len(students) - len(pending)
    if completed_count:
        info_message(
            f"{completed_count} طلباء کا آج کا تعلیمی کام پہلے سے محفوظ ہے۔ "
            "باقی طلباء میں سے ایک طالب علم منتخب کریں۔"
        )

    pending = pending.reset_index(drop=True)

    student_labels = pending.apply(
        lambda row: (
            f"{_clean(row.get('StudentName'))} — ولد "
            f"{_clean(row.get('FatherName'))}"
        ),
        axis=1,
    ).tolist()

    selected_label = st.selectbox(
        "👤 طالب علم منتخب کریں",
        student_labels,
        key=f"daily_work_student_{teacher_username}_{date_str}",
    )

    selected_index = student_labels.index(selected_label)
    student = pending.iloc[selected_index]

    name = _clean(student.get("StudentName"))
    father = _clean(student.get("FatherName"))

    widget_prefix = (
        f"daily_work_{teacher_username}_{date_str}_{selected_index}"
    )

    st.markdown(f"### {name} — ولد {father}")
    st.caption(
        "طالب علم کا کام سننے کے فوراً بعد محفوظ کریں۔ "
        "جو کام نہیں ہوا اس کے خانے خالی چھوڑ دیں۔"
    )

    s1, s2, s3, s4 = st.tabs(["سبق", "سبقی", "منزل", "پاؤ"])

    with s1:
        c1, c2 = st.columns(2)
        sabaq_surah = c1.text_input(
            "سورت",
            key=f"{widget_prefix}_ss",
        )
        sabaq_ayah = c2.text_input(
            "آیت/آیات",
            key=f"{widget_prefix}_sa",
        )

    with s2:
        c1, c2 = st.columns(2)
        sabqi_surah = c1.text_input(
            "سورت",
            key=f"{widget_prefix}_qs",
        )
        sabqi_ayah = c2.text_input(
            "آیت/آیات",
            key=f"{widget_prefix}_qa",
        )

    with s3:
        c1, c2 = st.columns(2)

        manzil_juz = c1.selectbox(
            "پارہ",
            [""] + config.JUZ_NUMBERS,
            key=f"{widget_prefix}_mj",
        )

        manzil_amount = c2.selectbox(
            "مقدار",
            ["", "مکمل", "نصف", "پاؤ"],
            key=f"{widget_prefix}_ma",
        )

        if manzil_amount == "نصف":
            manzil_half = st.selectbox(
                "نصف منتخب کریں",
                ["", "نصف اول", "نصف دوم"],
                key=f"{widget_prefix}_mh",
            )
        elif manzil_amount == "پاؤ":
            manzil_half = st.selectbox(
                "پاؤ منتخب کریں",
                ["", "پاؤ 1", "پاؤ 2", "پاؤ 3", "پاؤ 4"],
                key=f"{widget_prefix}_mh",
            )
        else:
            manzil_half = ""

    with s4:
        c1, c2 = st.columns(2)
        pao_juz = c1.selectbox(
            "پارہ",
            [""] + config.JUZ_NUMBERS,
            key=f"{widget_prefix}_pj",
        )
        pao_quarter = c2.selectbox(
            "پاؤ نمبر",
            [""] + config.PAO_QUARTERS,
            key=f"{widget_prefix}_pq",
        )

    submitted = st.button(
        "💾 اس طالب علم کا تعلیمی کام محفوظ کریں",
        key=f"{widget_prefix}_save",
        use_container_width=True,
        type="primary",
    )

    if not submitted:
        return

    record = {
        "StudentName": name,
        "FatherName": father,
        "SabaqSurah": sabaq_surah,
        "SabaqAyah": sabaq_ayah,
        "SabqiSurah": sabqi_surah,
        "SabqiAyah": sabqi_ayah,
        "ManzilJuz": manzil_juz,
        "ManzilAmount": manzil_amount,
        "ManzilHalf": manzil_half,
        "PaoJuz": pao_juz,
        "PaoQuarter": pao_quarter,
    }

    with st.spinner("تعلیمی کام محفوظ کیا جا رہا ہے..."):
        success = sheets.submit_daily_work(
            date_str,
            teacher_username,
            teacher_name,
            [record],
        )

    if success:
        sheets.add_log(
            auth.current_username(),
            f"روزانہ تعلیمی کام محفوظ کیا: {date_str} — "
            f"{name} ولد {father} — استاد {teacher_name}",
        )
        success_message(
            f"{name} ولد {father} کا تعلیمی کام کامیابی سے محفوظ ہو گیا۔"
        )
        st.rerun()
    else:
        error_message("تعلیمی کام محفوظ کرنے میں خرابی پیش آئی۔")


# ==================================================
# استاد کی ترمیم
# ==================================================
def render_teacher_edit_section(
    teacher_username: str,
    teacher_name: str,
):
    today = today_str()
    attendance_df = sheets.get_all_attendance()

    if attendance_df.empty:
        info_message("آج کی کوئی حاضری موجود نہیں۔")
        return

    required = {
        "Date", "AttendanceSession", "StudentName", "FatherName",
        "TeacherUsername", "Status"
    }
    if not required.issubset(attendance_df.columns):
        error_message("حاضری کی شیٹ کے کالم نامکمل ہیں۔")
        return

    records = attendance_df[
        (attendance_df["Date"].astype(str).str.strip() == today)
        & (
            attendance_df["TeacherUsername"].astype(str).map(_normalise)
            == _teacher_key(teacher_username)
        )
    ].copy()

    if records.empty:
        info_message("آپ نے آج کوئی حاضری درج نہیں کی۔")
        return

    session = st.selectbox(
        "حاضری کا وقت",
        config.ATTENDANCE_SESSIONS,
        key=f"teacher_edit_session_{teacher_username}",
    )
    records = records[
        records["AttendanceSession"].astype(str).str.strip() == session
    ]

    if records.empty:
        info_message(f"آج کی {session} موجود نہیں۔")
        return

    st.caption(f"استاد: {teacher_name} — {today}")
    for index, (_, record) in enumerate(records.iterrows()):
        name = _clean(record.get("StudentName"))
        father = _clean(record.get("FatherName"))
        current = _clean(record.get("Status"))
        status_index = (
            config.ATTENDANCE_STATUSES.index(current)
            if current in config.ATTENDANCE_STATUSES else 0
        )

        c1, c2, c3 = st.columns([3, 2, 1])
        c1.markdown(f"**{name}**  \nوالد: {father}")
        new_status = c2.selectbox(
            "حیثیت",
            config.ATTENDANCE_STATUSES,
            index=status_index,
            key=f"teacher_att_edit_{session}_{index}_{name}_{father}",
            label_visibility="collapsed",
        )
        clicked = c3.button(
            "محفوظ کریں",
            key=f"teacher_att_save_{session}_{index}_{name}_{father}",
        )

        if clicked:
            if new_status == current:
                info_message("حیثیت میں کوئی تبدیلی نہیں کی گئی۔")
                continue
            success = sheets.update_attendance_record(
                today,
                name,
                father,
                teacher_username,
                new_status,
                session,
            )
            if success:
                sheets.add_log(
                    auth.current_username(),
                    f"اپنی {session} میں ترمیم: {name} ولد {father} — {new_status}",
                )
                success_message(f"{name} کی حاضری اپ ڈیٹ ہو گئی۔")
                st.rerun()
            else:
                error_message("حاضری اپ ڈیٹ نہیں ہو سکی۔")


def render_teacher_daily_work_edit_section(
    teacher_username: str,
    teacher_name: str,
):
    today = today_str()
    work_df = sheets.get_all_daily_work()
    if work_df.empty:
        info_message("آج کا کوئی تعلیمی ریکارڈ موجود نہیں۔")
        return

    required = {"Date", "StudentName", "FatherName", "TeacherUsername"}
    if not required.issubset(work_df.columns):
        error_message("تعلیمی کام کی شیٹ کے کالم نامکمل ہیں۔")
        return

    records = work_df[
        (work_df["Date"].astype(str).str.strip() == today)
        & (
            work_df["TeacherUsername"].astype(str).map(_normalise)
            == _teacher_key(teacher_username)
        )
    ].copy()

    if records.empty:
        info_message("آپ نے آج کوئی تعلیمی کام درج نہیں کیا۔")
        return

    labels = [
        f"{_clean(row.get('StudentName'))} ولد {_clean(row.get('FatherName'))}"
        for _, row in records.iterrows()
    ]
    selected_label = st.selectbox(
        "طالب علم منتخب کریں", labels, key="teacher_work_edit_student"
    )
    selected_index = labels.index(selected_label)
    row = records.iloc[selected_index]

    _render_daily_work_editor(
        row=row,
        key_prefix="teacher_work_edit",
        allow_delete=False,
        teacher_username=teacher_username,
        teacher_name=teacher_name,
    )


# ==================================================
# منتظم کا مرکزی صفحہ
# ==================================================
def render_admin_attendance_page():
    require_login()
    if not auth.is_admin():
        error_message("یہ صفحہ صرف منتظم کے لیے مخصوص ہے۔")
        st.stop()

    st.title("📅 حاضری اور تعلیمی کام کا مکمل ریکارڈ")
    tabs = st.tabs(
        [
            "📋 حاضری کا ریکارڈ",
            "📖 تعلیمی کام",
            "➕ استاد کی طرف سے اندراج",
            "📊 شماریات",
        ]
    )

    with tabs[0]:
        render_admin_filters_and_records()
    with tabs[1]:
        render_admin_daily_work_records()
    with tabs[2]:
        render_admin_mark_on_behalf()
    with tabs[3]:
        render_attendance_statistics()


def render_admin_filters_and_records():
    df = sheets.get_all_attendance()
    if df.empty:
        info_message("ابھی تک کوئی حاضری ریکارڈ موجود نہیں۔")
        return

    col1, col2, col3, col4 = st.columns(4)
    date_filter = col1.date_input(
        "تاریخ", value=None, key="admin_att_date_filter"
    )
    session_filter = col2.selectbox(
        "حاضری کا وقت", ["تمام"] + config.ATTENDANCE_SESSIONS,
        key="admin_att_session_filter",
    )
    teacher_options = ["تمام"] + sorted(
        [x for x in df.get("TeacherName", pd.Series(dtype=str)).astype(str).unique() if x]
    )
    teacher_filter = col3.selectbox(
        "استاد", teacher_options, key="admin_att_teacher_filter"
    )
    status_filter = col4.selectbox(
        "حیثیت", ["تمام"] + config.ATTENDANCE_STATUSES,
        key="admin_att_status_filter",
    )

    query = st.text_input(
        "🔍 طالب علم یا والد کے نام سے تلاش کریں",
        key="admin_att_search",
    ).strip()

    filtered = df.copy()
    if date_filter:
        filtered = filtered[filtered["Date"].astype(str) == str(date_filter)]
    if session_filter != "تمام":
        filtered = filtered[
            filtered["AttendanceSession"].astype(str) == session_filter
        ]
    if teacher_filter != "تمام":
        filtered = filtered[
            filtered["TeacherName"].astype(str) == teacher_filter
        ]
    if status_filter != "تمام":
        filtered = filtered[filtered["Status"].astype(str) == status_filter]
    if query:
        mask = (
            filtered["StudentName"].astype(str).str.contains(query, case=False, na=False)
            | filtered["FatherName"].astype(str).str.contains(query, case=False, na=False)
        )
        filtered = filtered[mask]

    display_attendance_table(filtered)
    st.divider()
    st.subheader("✏️ حاضری میں ترمیم یا حذف")
    render_edit_delete_section(filtered, "admin_attendance")


def render_admin_search():
    """پرانے app.py یا دوسرے modules کے لیے برقرار رکھا گیا فنکشن۔"""
    render_admin_filters_and_records()


def render_admin_daily_work_records():
    df = sheets.get_all_daily_work()
    if df.empty:
        info_message("ابھی تک کوئی تعلیمی ریکارڈ موجود نہیں۔")
        return

    c1, c2 = st.columns(2)
    date_filter = c1.date_input(
        "تاریخ", value=None, key="admin_work_date_filter"
    )
    teacher_options = ["تمام"] + sorted(
        [x for x in df.get("TeacherName", pd.Series(dtype=str)).astype(str).unique() if x]
    )
    teacher_filter = c2.selectbox(
        "استاد", teacher_options, key="admin_work_teacher_filter"
    )
    query = st.text_input(
        "🔍 طالب علم یا والد کے نام سے تلاش کریں",
        key="admin_work_search",
    ).strip()

    filtered = df.copy()
    if date_filter:
        filtered = filtered[filtered["Date"].astype(str) == str(date_filter)]
    if teacher_filter != "تمام":
        filtered = filtered[
            filtered["TeacherName"].astype(str) == teacher_filter
        ]
    if query:
        mask = (
            filtered["StudentName"].astype(str).str.contains(query, case=False, na=False)
            | filtered["FatherName"].astype(str).str.contains(query, case=False, na=False)
        )
        filtered = filtered[mask]

    display_daily_work_table(filtered)
    if filtered.empty:
        return

    st.divider()
    st.subheader("✏️ تعلیمی ریکارڈ میں ترمیم یا حذف")
    working = filtered.reset_index(drop=True).copy()
    labels = working.apply(
        lambda row: (
            f"{_clean(row.get('Date'))} | {_clean(row.get('StudentName'))} "
            f"ولد {_clean(row.get('FatherName'))} | {_clean(row.get('TeacherName'))}"
        ),
        axis=1,
    ).tolist()
    selected = st.selectbox(
        "ریکارڈ منتخب کریں", labels, key="admin_work_record_select"
    )
    row = working.iloc[labels.index(selected)]
    _render_daily_work_editor(
        row=row,
        key_prefix="admin_work_editor",
        allow_delete=True,
        teacher_username=_clean(row.get("TeacherUsername")),
        teacher_name=_clean(row.get("TeacherName")),
    )


def render_admin_mark_on_behalf():
    teachers = _get_teacher_records()
    if not teachers:
        info_message("کوئی فعال استاد موجود نہیں۔")
        return

    usernames = [x["Username"] for x in teachers]
    names = {x["Username"]: x["FullName"] for x in teachers}
    selected_username = st.selectbox(
        "استاد منتخب کریں",
        usernames,
        format_func=lambda x: names.get(x, x),
        key="admin_teacher_on_behalf",
    )
    selected_name = names.get(selected_username, selected_username)

    sub_tabs = st.tabs(["حاضری", "تعلیمی کام"])
    with sub_tabs[0]:
        render_marking_form(selected_username, selected_name)
    with sub_tabs[1]:
        render_daily_work_form(selected_username, selected_name)


def render_attendance_statistics():
    selected_date = st.date_input(
        "تاریخ منتخب کریں",
        value=pd.to_datetime(today_str()),
        key="attendance_stats_date",
    )
    date_str = str(selected_date)
    attendance_df = sheets.get_all_attendance()
    active_students = sheets.get_active_students()
    total_students = len(active_students)

    if attendance_df.empty:
        day = pd.DataFrame()
    else:
        day = attendance_df[
            attendance_df["Date"].astype(str).str.strip() == date_str
        ].copy()

    session = st.selectbox(
        "حاضری کا وقت",
        config.ATTENDANCE_SESSIONS,
        key="attendance_stats_session",
    )
    if not day.empty:
        day = day[day["AttendanceSession"].astype(str) == session]

    counts = {
        status: int((day["Status"].astype(str) == status).sum())
        if not day.empty else 0
        for status in config.ATTENDANCE_STATUSES
    }
    submitted_students = len(day)
    missing = max(total_students - submitted_students, 0)

    cols = st.columns(6)
    cards = [
        ("کل فعال طلباء", total_students, "🎓"),
        ("حاضر", counts.get(config.STATUS_PRESENT, 0), "✅"),
        ("غیر حاضر", counts.get(config.STATUS_ABSENT, 0), "❌"),
        ("تاخیر سے حاضر", counts.get(config.STATUS_LATE, 0), "⏰"),
        ("رخصت", counts.get(config.STATUS_LEAVE, 0), "📝"),
        ("غیر درج شدہ", missing, "⚠️"),
    ]
    for column, (title, value, icon) in zip(cols, cards):
        with column:
            render_stat_card(title, value, icon)

    if day.empty:
        info_message(f"{date_str} کی {session} ابھی درج نہیں ہوئی۔")
    else:
        display_attendance_table(day)


# ==================================================
# مشترکہ جدول اور ترمیم کے فنکشنز
# ==================================================
def display_attendance_table(df: pd.DataFrame):
    if df.empty:
        info_message("کوئی ریکارڈ نہیں ملا۔")
        return

    columns = [x for x in config.ATTENDANCE_HEADERS if x in df.columns]
    display_df = df[columns].rename(columns=ATTENDANCE_COLUMN_LABELS)
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.caption(f"کل ریکارڈز: {len(df)}")


def display_daily_work_table(df: pd.DataFrame):
    if df.empty:
        info_message("کوئی ریکارڈ نہیں ملا۔")
        return

    columns = [x for x in config.DAILY_WORK_HEADERS if x in df.columns]
    display_df = df[columns].rename(columns=DAILY_WORK_COLUMN_LABELS)
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.caption(f"کل ریکارڈز: {len(df)}")


def render_edit_delete_section(
    filtered_df: pd.DataFrame,
    key_prefix: str,
):
    if filtered_df.empty:
        info_message("ترمیم کے لیے کوئی ریکارڈ دستیاب نہیں۔")
        return

    working = filtered_df.reset_index(drop=True).copy()
    working["_label"] = working.apply(
        lambda row: (
            f"{_clean(row.get('Date'))} | "
            f"{_clean(row.get('AttendanceSession'))} | "
            f"{_clean(row.get('StudentName'))} ولد "
            f"{_clean(row.get('FatherName'))} | "
            f"{_clean(row.get('TeacherName'))}"
        ),
        axis=1,
    )
    selected_label = st.selectbox(
        "ریکارڈ منتخب کریں",
        working["_label"].tolist(),
        key=f"{key_prefix}_select",
    )
    row = working[working["_label"] == selected_label].iloc[0]

    selected_date = _clean(row.get("Date"))
    session = _clean(row.get("AttendanceSession"))
    name = _clean(row.get("StudentName"))
    father = _clean(row.get("FatherName"))
    username = _clean(row.get("TeacherUsername"))
    current = _clean(row.get("Status"))
    status_index = (
        config.ATTENDANCE_STATUSES.index(current)
        if current in config.ATTENDANCE_STATUSES else 0
    )

    c1, c2 = st.columns(2)
    with c1:
        new_status = st.selectbox(
            "نئی حیثیت",
            config.ATTENDANCE_STATUSES,
            index=status_index,
            key=f"{key_prefix}_status",
        )
        if st.button(
            "✅ حیثیت اپ ڈیٹ کریں",
            key=f"{key_prefix}_update",
            use_container_width=True,
        ):
            success = sheets.update_attendance_record(
                selected_date,
                name,
                father,
                username,
                new_status,
                session,
            )
            if success:
                sheets.add_log(
                    auth.current_username(),
                    f"منتظم نے {session} میں ترمیم کی: "
                    f"{name} ولد {father} — {new_status} ({selected_date})",
                )
                success_message("حاضری کامیابی سے اپ ڈیٹ ہو گئی۔")
                st.rerun()
            else:
                error_message("حاضری اپ ڈیٹ نہیں ہو سکی۔")

    with c2:
        confirm_key = f"{key_prefix}_confirm_delete"
        if st.button(
            "🗑️ یہ ریکارڈ حذف کریں",
            key=f"{key_prefix}_delete",
            use_container_width=True,
        ):
            st.session_state[confirm_key] = selected_label

        if st.session_state.get(confirm_key) == selected_label:
            warning_message(
                f"کیا آپ واقعی {name} ولد {father} کی {session} حذف کرنا چاہتے ہیں؟"
            )
            yes, no = st.columns(2)
            if yes.button(
                "ہاں، حذف کریں",
                key=f"{key_prefix}_yes",
                use_container_width=True,
            ):
                success = sheets.delete_attendance_record(
                    selected_date,
                    name,
                    father,
                    username,
                    session,
                )
                if success:
                    sheets.add_log(
                        auth.current_username(),
                        f"منتظم نے {session} حذف کی: "
                        f"{name} ولد {father} ({selected_date})",
                    )
                    st.session_state.pop(confirm_key, None)
                    success_message("ریکارڈ کامیابی سے حذف ہو گیا۔")
                    st.rerun()
                else:
                    error_message("ریکارڈ حذف نہیں ہو سکا۔")
            if no.button(
                "منسوخ کریں",
                key=f"{key_prefix}_no",
                use_container_width=True,
            ):
                st.session_state.pop(confirm_key, None)
                st.rerun()


def _select_index(options: list, value) -> int:
    cleaned = _clean(value)
    return options.index(cleaned) if cleaned in options else 0


def _render_daily_work_editor(
    row: pd.Series,
    key_prefix: str,
    allow_delete: bool,
    teacher_username: str,
    teacher_name: str,
):
    date = _clean(row.get("Date"))
    name = _clean(row.get("StudentName"))
    father = _clean(row.get("FatherName"))

    unique_prefix = (
        f"{key_prefix}_{_normalise(name)}_{_normalise(father)}_{date}"
    )

    st.markdown(f"**{name}** — ولد {father} — {date}")

    c1, c2 = st.columns(2)
    sabaq_surah = c1.text_input(
        "سبق: سورت",
        value=_clean(row.get("SabaqSurah")),
        key=f"{unique_prefix}_sabaq_surah",
    )
    sabaq_ayah = c2.text_input(
        "سبق: آیت/آیات",
        value=_clean(row.get("SabaqAyah")),
        key=f"{unique_prefix}_sabaq_ayah",
    )

    c1, c2 = st.columns(2)
    sabqi_surah = c1.text_input(
        "سبقی: سورت",
        value=_clean(row.get("SabqiSurah")),
        key=f"{unique_prefix}_sabqi_surah",
    )
    sabqi_ayah = c2.text_input(
        "سبقی: آیت/آیات",
        value=_clean(row.get("SabqiAyah")),
        key=f"{unique_prefix}_sabqi_ayah",
    )

    juz_options = [""] + [str(x) for x in config.JUZ_NUMBERS]
    amount_options = ["", "مکمل", "نصف", "پاؤ"]
    half_options = ["", "نصف اول", "نصف دوم"]
    manzil_quarter_options = [
        "",
        "پاؤ 1",
        "پاؤ 2",
        "پاؤ 3",
        "پاؤ 4",
    ]
    quarter_options = [""] + [str(x) for x in config.PAO_QUARTERS]

    current_amount = _clean(row.get("ManzilAmount"))
    current_part = _clean(row.get("ManzilHalf"))

    c1, c2 = st.columns(2)

    manzil_juz = c1.selectbox(
        "منزل: پارہ",
        juz_options,
        index=_select_index(juz_options, row.get("ManzilJuz")),
        key=f"{unique_prefix}_manzil_juz",
    )

    manzil_amount = c2.selectbox(
        "منزل: مقدار",
        amount_options,
        index=_select_index(amount_options, current_amount),
        key=f"{unique_prefix}_manzil_amount",
    )

    if manzil_amount == "نصف":
        manzil_half = st.selectbox(
            "منزل: نصف منتخب کریں",
            half_options,
            index=_select_index(half_options, current_part),
            key=f"{unique_prefix}_manzil_part",
        )
    elif manzil_amount == "پاؤ":
        manzil_half = st.selectbox(
            "منزل: پاؤ منتخب کریں",
            manzil_quarter_options,
            index=_select_index(manzil_quarter_options, current_part),
            key=f"{unique_prefix}_manzil_part",
        )
    else:
        manzil_half = ""

    c1, c2 = st.columns(2)
    pao_juz = c1.selectbox(
        "پاؤ: پارہ",
        juz_options,
        index=_select_index(juz_options, row.get("PaoJuz")),
        key=f"{unique_prefix}_pao_juz",
    )
    pao_quarter = c2.selectbox(
        "پاؤ نمبر",
        quarter_options,
        index=_select_index(quarter_options, row.get("PaoQuarter")),
        key=f"{unique_prefix}_pao_quarter",
    )

    save = st.button(
        "💾 تبدیلیاں محفوظ کریں",
        key=f"{unique_prefix}_save",
        use_container_width=True,
        type="primary",
    )

    if save:
        success = sheets.update_daily_work_record(
            date=date,
            student_name=name,
            father_name=father,
            teacher_username=teacher_username,
            teacher_name=teacher_name,
            sabaq_surah=sabaq_surah,
            sabaq_ayah=sabaq_ayah,
            sabqi_surah=sabqi_surah,
            sabqi_ayah=sabqi_ayah,
            manzil_juz=manzil_juz,
            manzil_amount=manzil_amount,
            manzil_half=manzil_half,
            pao_juz=pao_juz,
            pao_quarter=pao_quarter,
        )

        if success:
            sheets.add_log(
                auth.current_username(),
                f"تعلیمی ریکارڈ میں ترمیم: {name} ولد {father} ({date})",
            )
            success_message("تعلیمی ریکارڈ کامیابی سے اپ ڈیٹ ہو گیا۔")
            st.rerun()
        else:
            error_message("تعلیمی ریکارڈ اپ ڈیٹ نہیں ہو سکا۔")

    if allow_delete:
        confirm_key = f"{unique_prefix}_delete_confirm"

        if st.button(
            "🗑️ تعلیمی ریکارڈ حذف کریں",
            key=f"{unique_prefix}_delete_button",
            use_container_width=True,
        ):
            st.session_state[confirm_key] = True

        if st.session_state.get(confirm_key):
            warning_message("کیا آپ واقعی یہ تعلیمی ریکارڈ حذف کرنا چاہتے ہیں؟")

            yes, no = st.columns(2)

            if yes.button(
                "ہاں، حذف کریں",
                key=f"{unique_prefix}_delete_yes",
                use_container_width=True,
            ):
                success = sheets.delete_daily_work_record(
                    date,
                    name,
                    father,
                    teacher_username,
                )

                if success:
                    sheets.add_log(
                        auth.current_username(),
                        f"تعلیمی ریکارڈ حذف کیا: "
                        f"{name} ولد {father} ({date})",
                    )
                    st.session_state.pop(confirm_key, None)
                    success_message("تعلیمی ریکارڈ حذف ہو گیا۔")
                    st.rerun()
                else:
                    error_message("تعلیمی ریکارڈ حذف نہیں ہو سکا۔")

            if no.button(
                "منسوخ کریں",
                key=f"{unique_prefix}_delete_no",
                use_container_width=True,
            ):
                st.session_state.pop(confirm_key, None)
                st.rerun()
