# dashboard.py
"""
مدرسہ ڈیش بورڈ
==================================================
منتظم کے لیے پورے مدرسہ اور استاد کے لیے اپنے طلباء کی موجودہ صورتحال
دکھاتا ہے۔ ڈیش بورڈ صبح/دوپہر کی حاضری، روزانہ تعلیمی کام، تعلیمی ایام،
حالیہ ریکارڈ اور سرگرمی لاگز کو updated config.py اور sheets.py کے مطابق
استعمال کرتا ہے۔

اہم اصول:
    - RollNumber استعمال نہیں ہوتا۔
    - حاضری کے دونوں سیشن الگ شمار ہوتے ہیں۔
    - جمعہ تعلیمی دن میں شامل نہیں ہوتا۔
    - استاد کو صرف اپنے مقرر کردہ طلباء اور اپنے ریکارڈ دکھائے جاتے ہیں۔
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import config
import sheets
from utils import format_date, render_stat_card, require_login, today_str


ATTENDANCE_LABELS = {
    "Date": "تاریخ",
    "AttendanceSession": "حاضری کا وقت",
    "StudentName": "طالب علم",
    "FatherName": "والد کا نام",
    "TeacherName": "استاد",
    "Status": "حیثیت",
    "TimeSubmitted": "وقت",
}

DAILY_WORK_LABELS = {
    "Date": "تاریخ",
    "StudentName": "طالب علم",
    "FatherName": "والد کا نام",
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
    "TimeSubmitted": "وقت",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalise(value: Any) -> str:
    return _clean(value).casefold()


def _is_active(value: Any) -> bool:
    return _normalise(value) in {"true", "1", "yes", "فعال"}


def _safe_date(value: Any) -> date | None:
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


def _month_bounds(reference_date: date) -> tuple[date, date]:
    last_day = calendar.monthrange(reference_date.year, reference_date.month)[1]
    return (
        reference_date.replace(day=1),
        reference_date.replace(day=last_day),
    )


def _educational_days(start_date: date, end_date: date) -> int:
    """جمعہ کے علاوہ تاریخوں کی تعداد۔"""
    if end_date < start_date:
        return 0

    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    return int(sum(item.weekday() != config.FRIDAY_WEEKDAY for item in dates))


def _filter_date(df: pd.DataFrame, selected_date: str) -> pd.DataFrame:
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame(columns=df.columns)

    return df[
        df["Date"].astype(str).str.strip() == _clean(selected_date)
    ].copy()


def _filter_month(df: pd.DataFrame, month_prefix: str) -> pd.DataFrame:
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame(columns=df.columns)

    return df[
        df["Date"].astype(str).str.strip().str.startswith(month_prefix)
    ].copy()


def _active_students(students_df: pd.DataFrame) -> pd.DataFrame:
    if students_df.empty:
        return students_df.copy()

    if "Status" not in students_df.columns:
        return students_df.copy()

    return students_df[
        students_df["Status"].astype(str).str.strip()
        == config.STUDENT_STATUS_ACTIVE
    ].copy()


def _teacher_students(
    students_df: pd.DataFrame,
    teacher_username: str,
) -> pd.DataFrame:
    active_df = _active_students(students_df)

    if active_df.empty or "AssignedTeacher" not in active_df.columns:
        return active_df

    return active_df[
        active_df["AssignedTeacher"].astype(str).map(_normalise)
        == _normalise(teacher_username)
    ].copy()


def _teacher_records(
    df: pd.DataFrame,
    teacher_username: str,
) -> pd.DataFrame:
    if df.empty or "TeacherUsername" not in df.columns:
        return pd.DataFrame(columns=df.columns)

    return df[
        df["TeacherUsername"].astype(str).map(_normalise)
        == _normalise(teacher_username)
    ].copy()


def _count_status(df: pd.DataFrame, status: str) -> int:
    if df.empty or "Status" not in df.columns:
        return 0
    return int(
        (
            df["Status"].astype(str).str.strip()
            == _clean(status)
        ).sum()
    )


def _attendance_rate(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0

    counted = len(df)
    if counted == 0:
        return 0.0

    attended = _count_status(df, config.STATUS_PRESENT) + _count_status(
        df,
        config.STATUS_LATE,
    )
    return round((attended / counted) * 100, 1)


def _session_records(
    attendance_df: pd.DataFrame,
    selected_date: str,
    session_name: str,
) -> pd.DataFrame:
    day_df = _filter_date(attendance_df, selected_date)

    if day_df.empty or "AttendanceSession" not in day_df.columns:
        return pd.DataFrame(columns=day_df.columns)

    return day_df[
        day_df["AttendanceSession"].astype(str).str.strip()
        == session_name
    ].copy()


def _unique_students_count(df: pd.DataFrame) -> int:
    required = {"StudentName", "FatherName"}
    if df.empty or not required.issubset(df.columns):
        return 0

    return int(
        df[["StudentName", "FatherName"]]
        .astype(str)
        .drop_duplicates()
        .shape[0]
    )


def _daily_work_completion_counts(
    daily_work_df: pd.DataFrame,
    total_students: int,
) -> dict[str, int]:
    """آج کے تعلیمی کام میں ہر حصے کی جمع شدہ اور باقی تعداد۔"""
    result: dict[str, int] = {}

    checks = {
        config.WORK_SABAQ: ["SabaqSurah", "SabaqAyah"],
        config.WORK_SABQI: ["SabqiSurah", "SabqiAyah"],
        config.WORK_MANZIL: ["ManzilJuz", "ManzilAmount"],
        config.WORK_PAO: ["PaoJuz", "PaoQuarter"],
    }

    for label, columns in checks.items():
        if daily_work_df.empty or not set(columns).issubset(daily_work_df.columns):
            submitted = 0
        else:
            complete_mask = pd.Series(True, index=daily_work_df.index)
            for column in columns:
                complete_mask &= (
                    daily_work_df[column].astype(str).str.strip() != ""
                )
            submitted = _unique_students_count(daily_work_df[complete_mask])

        result[f"{label}_submitted"] = submitted
        result[f"{label}_missing"] = max(total_students - submitted, 0)

    return result


def _display_header(full_name: str, is_admin: bool) -> None:
    school_name = sheets.get_setting(
        "school_name",
        config.DEFAULT_SCHOOL_NAME,
    )
    role_text = "منتظم" if is_admin else "استاد"

    st.markdown(
        f"""
        <div class="dashboard-header">
            <div class="dashboard-title">🕌 {_clean(school_name)}</div>
            <div class="dashboard-subtitle">
                السلام علیکم، {_clean(full_name)} 👋
            </div>
            <div class="dashboard-text">
                {role_text} ڈیش بورڈ — مدرسہ کی تازہ صورتحال ایک نظر میں
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard():
    """صارف کے کردار کے مطابق منتظم یا استاد ڈیش بورڈ دکھائیں۔"""
    require_login()

    if auth.is_admin():
        render_admin_dashboard()
        return

    if auth.is_teacher():
        render_teacher_dashboard()
        return

    st.error("⚠️ آپ کے صارف کردار کے لیے ڈیش بورڈ دستیاب نہیں۔")
    st.stop()


def render_admin_dashboard():
    _display_header(auth.current_fullname(), is_admin=True)

    with st.spinner("اعداد و شمار لوڈ ہو رہے ہیں..."):
        students_df = sheets.get_all_students()
        attendance_df = sheets.get_all_attendance()
        daily_work_df = sheets.get_all_daily_work()
        users_df = sheets.get_all_users()
        logs_df = sheets.get_all_logs()

    _render_dashboard_body(
        students_df=students_df,
        attendance_df=attendance_df,
        daily_work_df=daily_work_df,
        users_df=users_df,
        logs_df=logs_df,
        teacher_username=None,
        is_admin=True,
    )


def render_teacher_dashboard():
    teacher_username = auth.current_username()
    _display_header(auth.current_fullname(), is_admin=False)

    with st.spinner("اعداد و شمار لوڈ ہو رہے ہیں..."):
        students_df = _teacher_students(
            sheets.get_all_students(),
            teacher_username,
        )
        attendance_df = _teacher_records(
            sheets.get_all_attendance(),
            teacher_username,
        )
        daily_work_df = _teacher_records(
            sheets.get_all_daily_work(),
            teacher_username,
        )

    _render_dashboard_body(
        students_df=students_df,
        attendance_df=attendance_df,
        daily_work_df=daily_work_df,
        users_df=pd.DataFrame(),
        logs_df=pd.DataFrame(),
        teacher_username=teacher_username,
        is_admin=False,
    )


def _render_dashboard_body(
    students_df: pd.DataFrame,
    attendance_df: pd.DataFrame,
    daily_work_df: pd.DataFrame,
    users_df: pd.DataFrame,
    logs_df: pd.DataFrame,
    teacher_username: str | None,
    is_admin: bool,
) -> None:
    today = today_str()
    today_date = _safe_date(today) or date.today()
    month_start, month_end = _month_bounds(today_date)
    month_prefix = today_date.strftime("%Y-%m")

    active_students_df = _active_students(students_df)
    total_students = len(active_students_df)

    total_teachers = 0
    if is_admin and not users_df.empty and "Role" in users_df.columns:
        teacher_mask = (
            users_df["Role"].astype(str).str.strip()
            == config.ROLE_TEACHER
        )
        if "Active" in users_df.columns:
            teacher_mask &= users_df["Active"].map(_is_active)
        total_teachers = int(teacher_mask.sum())

    educational_days_month = _educational_days(month_start, month_end)
    educational_days_elapsed = _educational_days(month_start, today_date)

    morning_df = _session_records(
        attendance_df,
        today,
        config.ATTENDANCE_SESSION_MORNING,
    )
    afternoon_df = _session_records(
        attendance_df,
        today,
        config.ATTENDANCE_SESSION_AFTERNOON,
    )
    today_work_df = _filter_date(daily_work_df, today)

    morning_marked = _unique_students_count(morning_df)
    afternoon_marked = _unique_students_count(afternoon_df)
    morning_missing = max(total_students - morning_marked, 0)
    afternoon_missing = max(total_students - afternoon_marked, 0)

    work_counts = _daily_work_completion_counts(
        today_work_df,
        total_students,
    )

    row1 = st.columns(5)
    with row1[0]:
        render_stat_card("فعال طلباء", total_students, "🎓")
    with row1[1]:
        if is_admin:
            render_stat_card("فعال اساتذہ", total_teachers, "👨‍🏫")
        else:
            render_stat_card("میرے طلباء", total_students, "👥")
    with row1[2]:
        render_stat_card("ماہ کے تعلیمی ایام", educational_days_month, "📚")
    with row1[3]:
        render_stat_card("گزرے تعلیمی ایام", educational_days_elapsed, "🗓️")
    with row1[4]:
        render_stat_card("آج کی تاریخ", format_date(today), "📅")

    row2 = st.columns(4)
    with row2[0]:
        render_stat_card("صبح حاضری درج", morning_marked, "🌅")
    with row2[1]:
        render_stat_card("صبح حاضری باقی", morning_missing, "⚠️")
    with row2[2]:
        render_stat_card("دوپہر حاضری درج", afternoon_marked, "☀️")
    with row2[3]:
        render_stat_card("دوپہر حاضری باقی", afternoon_missing, "⚠️")

    if today_date.weekday() == config.FRIDAY_WEEKDAY:
        st.info("ℹ️ آج جمعہ ہے، اس لیے آج کو تعلیمی دن میں شمار نہیں کیا گیا۔")

    st.markdown("---")
    st.subheader("📖 آج کا تعلیمی کام")

    work_cols = st.columns(4)
    work_items = [
        (config.WORK_SABAQ, "📘"),
        (config.WORK_SABQI, "📗"),
        (config.WORK_MANZIL, "📙"),
        (config.WORK_PAO, "📒"),
    ]

    for column, (work_name, icon) in zip(work_cols, work_items):
        submitted = work_counts[f"{work_name}_submitted"]
        missing = work_counts[f"{work_name}_missing"]
        with column:
            render_stat_card(
                f"{work_name} درج / باقی",
                f"{submitted} / {missing}",
                icon,
            )

    st.markdown("---")
    _render_charts(
        attendance_df=attendance_df,
        morning_df=morning_df,
        afternoon_df=afternoon_df,
        month_prefix=month_prefix,
    )

    st.markdown("---")
    _render_recent_records(
        attendance_df=attendance_df,
        daily_work_df=daily_work_df,
        logs_df=logs_df,
        show_logs=is_admin,
    )


def _render_charts(
    attendance_df: pd.DataFrame,
    morning_df: pd.DataFrame,
    afternoon_df: pd.DataFrame,
    month_prefix: str,
) -> None:
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.subheader("🥧 آج کی حاضری کی تقسیم")

        today_combined = pd.concat(
            [morning_df, afternoon_df],
            ignore_index=True,
        )

        if today_combined.empty:
            st.info("ℹ️ آج کے لیے ابھی تک کوئی حاضری درج نہیں ہوئی۔")
        else:
            status_counts = pd.DataFrame(
                {
                    "حیثیت": config.ATTENDANCE_STATUSES,
                    "تعداد": [
                        _count_status(today_combined, status)
                        for status in config.ATTENDANCE_STATUSES
                    ],
                }
            )
            status_counts = status_counts[status_counts["تعداد"] > 0]

            figure = px.pie(
                status_counts,
                names="حیثیت",
                values="تعداد",
                color="حیثیت",
                color_discrete_map=config.ATTENDANCE_COLORS,
                hole=0.45,
            )
            figure.update_layout(
                font={"size": 14},
                margin={"t": 10, "b": 10, "l": 10, "r": 10},
                legend_title_text="حیثیت",
            )
            st.plotly_chart(figure, use_container_width=True)

            rate = _attendance_rate(today_combined)
            st.caption(f"آج مجموعی حاضری کی شرح: {rate}%")

    with chart_col2:
        st.subheader("📆 ماہانہ حاضری کا رجحان")
        monthly_df = _filter_month(attendance_df, month_prefix)

        if monthly_df.empty:
            st.info("ℹ️ اس مہینے کے لیے ابھی کوئی حاضری ڈیٹا موجود نہیں۔")
            return

        if "Status" not in monthly_df.columns:
            st.info("ℹ️ حاضری کی حیثیت کا کالم دستیاب نہیں۔")
            return

        attended_df = monthly_df[
            monthly_df["Status"].astype(str).str.strip().isin(
                [config.STATUS_PRESENT, config.STATUS_LATE]
            )
        ].copy()

        group_columns = ["Date"]
        if "AttendanceSession" in attended_df.columns:
            group_columns.append("AttendanceSession")

        daily_counts = (
            attended_df.groupby(group_columns)
            .size()
            .reset_index(name="تعداد")
        )

        if daily_counts.empty:
            st.info("ℹ️ اس مہینے میں حاضر طلباء کا ریکارڈ موجود نہیں۔")
            return

        if "AttendanceSession" in daily_counts.columns:
            figure = px.bar(
                daily_counts,
                x="Date",
                y="تعداد",
                color="AttendanceSession",
                barmode="group",
                labels={
                    "Date": "تاریخ",
                    "تعداد": "حاضر طلباء",
                    "AttendanceSession": "حاضری کا وقت",
                },
            )
        else:
            figure = px.bar(
                daily_counts,
                x="Date",
                y="تعداد",
                labels={"Date": "تاریخ", "تعداد": "حاضر طلباء"},
            )

        figure.update_layout(
            margin={"t": 10, "b": 10, "l": 10, "r": 10}
        )
        st.plotly_chart(figure, use_container_width=True)


def _render_recent_records(
    attendance_df: pd.DataFrame,
    daily_work_df: pd.DataFrame,
    logs_df: pd.DataFrame,
    show_logs: bool,
) -> None:
    tab_titles = ["🕘 حالیہ حاضری", "📖 حالیہ تعلیمی کام"]
    if show_logs:
        tab_titles.append("🧾 حالیہ سرگرمیاں")

    tabs = st.tabs(tab_titles)

    with tabs[0]:
        if attendance_df.empty:
            st.info("ℹ️ ابھی تک کوئی حاضری ریکارڈ موجود نہیں۔")
        else:
            sort_columns = [
                column
                for column in ["Date", "TimeSubmitted"]
                if column in attendance_df.columns
            ]
            recent_df = attendance_df.copy()
            if sort_columns:
                recent_df = recent_df.sort_values(
                    by=sort_columns,
                    ascending=False,
                )

            preferred_columns = [
                "Date",
                "AttendanceSession",
                "StudentName",
                "FatherName",
                "TeacherName",
                "Status",
                "TimeSubmitted",
            ]
            available_columns = [
                column for column in preferred_columns if column in recent_df.columns
            ]
            display_df = (
                recent_df[available_columns]
                .head(10)
                .rename(columns=ATTENDANCE_LABELS)
            )
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
            )

    with tabs[1]:
        if daily_work_df.empty:
            st.info("ℹ️ ابھی تک کوئی تعلیمی کام درج نہیں ہوا۔")
        else:
            sort_columns = [
                column
                for column in ["Date", "TimeSubmitted"]
                if column in daily_work_df.columns
            ]
            recent_work = daily_work_df.copy()
            if sort_columns:
                recent_work = recent_work.sort_values(
                    by=sort_columns,
                    ascending=False,
                )

            preferred_columns = [
                "Date",
                "StudentName",
                "FatherName",
                "TeacherName",
                "SabaqSurah",
                "SabaqAyah",
                "SabqiSurah",
                "SabqiAyah",
                "ManzilJuz",
                "ManzilAmount",
                "ManzilHalf",
                "PaoJuz",
                "PaoQuarter",
                "TimeSubmitted",
            ]
            available_columns = [
                column for column in preferred_columns if column in recent_work.columns
            ]
            display_df = (
                recent_work[available_columns]
                .head(10)
                .rename(columns=DAILY_WORK_LABELS)
            )
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
            )

    if show_logs:
        with tabs[2]:
            if logs_df.empty:
                st.info("ℹ️ ابھی تک کوئی سرگرمی لاگ موجود نہیں۔")
            else:
                sort_columns = [
                    column
                    for column in ["Date", "Time"]
                    if column in logs_df.columns
                ]
                recent_logs = logs_df.copy()
                if sort_columns:
                    recent_logs = recent_logs.sort_values(
                        by=sort_columns,
                        ascending=False,
                    )

                preferred_columns = ["Date", "Time", "Username", "Action"]
                available_columns = [
                    column for column in preferred_columns if column in recent_logs.columns
                ]
                display_logs = (
                    recent_logs[available_columns]
                    .head(10)
                    .rename(
                        columns={
                            "Date": "تاریخ",
                            "Time": "وقت",
                            "Username": "صارف",
                            "Action": "عمل",
                        }
                    )
                )
                st.dataframe(
                    display_logs,
                    use_container_width=True,
                    hide_index=True,
                )