# students.py
"""
طلباء کے انتظام کا صفحہ۔

اہم اصول:
- طالب علم کی شناخت StudentName + FatherName + AssignedTeacher سے ہوتی ہے۔
- Student ID / Roll Number استعمال نہیں ہوتا۔
- صرف منتظم طلباء شامل، تبدیل یا حذف کر سکتا ہے۔
- فعال اور غیر فعال طلباء دونوں دکھائے جا سکتے ہیں۔
- Excel اور PDF برآمد کی سہولت موجود ہے۔
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

import pandas as pd
import streamlit as st

import auth
import config
import sheets

try:
    from reports import dataframe_to_pdf_bytes, to_excel_bytes
except Exception:
    dataframe_to_pdf_bytes = None
    to_excel_bytes = None

from utils import (
    error_message,
    info_message,
    require_login,
    success_message,
    warning_message,
)


STUDENT_COLUMN_LABELS = {
    "StudentName": "طالب علم کا نام",
    "FatherName": "والد کا نام",
    "AssignedTeacher": "مقرر استاد",
    "Status": "حیثیت",
    "DateAdded": "داخلے کی تاریخ",
    "Notes": "نوٹس",
}


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _normalise(value: Any) -> str:
    return _clean(value).casefold()


def _student_key(student_name: Any, father_name: Any, teacher: Any) -> str:
    return (
        f"{_normalise(student_name)}|||"
        f"{_normalise(father_name)}|||"
        f"{_normalise(teacher)}"
    )


def _find_callable(*names: str) -> Callable | None:
    for name in names:
        func = getattr(sheets, name, None)
        if callable(func):
            return func
    return None


def _call_compatible(func: Callable, candidates: list[tuple[tuple, dict]]):
    """
    مختلف ممکنہ sheets.py signatures کے ساتھ محفوظ طریقے سے فنکشن چلائیں۔
    """
    last_error = None

    for args, kwargs in candidates:
        try:
            signature = inspect.signature(func)
            signature.bind_partial(*args, **kwargs)
        except (TypeError, ValueError):
            continue

        try:
            return func(*args, **kwargs)
        except TypeError as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error

    raise TypeError("اس فنکشن کے لیے مناسب arguments نہیں ملے۔")


def _get_all_students() -> pd.DataFrame:
    func = _find_callable(
        "get_all_students",
        "get_students",
        "fetch_students",
        "read_students",
    )

    if func is None:
        raise AttributeError(
            "sheets.py میں get_all_students() یا اس جیسا فنکشن موجود نہیں۔"
        )

    result = func()

    if result is None:
        return pd.DataFrame()

    if isinstance(result, pd.DataFrame):
        return result.copy()

    return pd.DataFrame(result)


def _get_teacher_records() -> list[dict]:
    func = _find_callable("get_all_users", "get_users", "fetch_users")
    if func is None:
        return []

    users = func()
    if users is None:
        return []

    users_df = users if isinstance(users, pd.DataFrame) else pd.DataFrame(users)
    if users_df.empty:
        return []

    required = {"Username", "FullName", "Role"}
    if not required.issubset(users_df.columns):
        return []

    teacher_role = getattr(config, "ROLE_TEACHER", "teacher")
    teachers = users_df[
        users_df["Role"].astype(str).str.strip() == teacher_role
    ].copy()

    if "Active" in teachers.columns:
        active = teachers["Active"].astype(str).str.strip().str.lower()
        teachers = teachers[active.isin(["true", "1", "yes", "فعال"])]

    records = []
    for _, row in teachers.iterrows():
        username = _clean(row.get("Username"))
        full_name = _clean(row.get("FullName")) or username
        if username:
            records.append(
                {
                    "Username": username,
                    "FullName": full_name,
                }
            )

    return records


def _status_options() -> list[str]:
    active = getattr(config, "STUDENT_STATUS_ACTIVE", "فعال")
    inactive = getattr(config, "STUDENT_STATUS_INACTIVE", "غیر فعال")
    return [active, inactive]


def _active_status() -> str:
    return getattr(config, "STUDENT_STATUS_ACTIVE", "فعال")


def _add_student(
    student_name: str,
    father_name: str,
    assigned_teacher: str,
    status: str,
    notes: str,
) -> bool:
    func = _find_callable(
        "add_student",
        "create_student",
        "insert_student",
        "save_student",
    )

    if func is None:
        raise AttributeError(
            "sheets.py میں add_student() یا اس جیسا فنکشن موجود نہیں۔"
        )

    record = {
        "StudentName": student_name,
        "FatherName": father_name,
        "AssignedTeacher": assigned_teacher,
        "Status": status,
        "Notes": notes,
    }

    result = _call_compatible(
        func,
        [
            ((record,), {}),
            ((), record),
            (
                (
                    student_name,
                    father_name,
                    assigned_teacher,
                    status,
                    notes,
                ),
                {},
            ),
            (
                (
                    student_name,
                    father_name,
                    assigned_teacher,
                    status,
                ),
                {},
            ),
            (
                (
                    student_name,
                    father_name,
                    assigned_teacher,
                ),
                {},
            ),
        ],
    )

    return True if result is None else bool(result)


def _update_student(
    old_name: str,
    old_father: str,
    old_teacher: str,
    new_name: str,
    new_father: str,
    new_teacher: str,
    new_status: str,
    notes: str,
) -> bool:
    func = _find_callable(
        "update_student",
        "update_student_record",
        "edit_student",
    )

    if func is None:
        raise AttributeError(
            "sheets.py میں update_student() یا اس جیسا فنکشن موجود نہیں۔"
        )

    updated_record = {
        "StudentName": new_name,
        "FatherName": new_father,
        "AssignedTeacher": new_teacher,
        "Status": new_status,
        "Notes": notes,
    }

    result = _call_compatible(
        func,
        [
            (
                (),
                {
                    "old_student_name": old_name,
                    "old_father_name": old_father,
                    "old_assigned_teacher": old_teacher,
                    "student_name": new_name,
                    "father_name": new_father,
                    "assigned_teacher": new_teacher,
                    "status": new_status,
                    "notes": notes,
                },
            ),
            (
                (),
                {
                    "student_name": old_name,
                    "father_name": old_father,
                    "assigned_teacher": old_teacher,
                    "new_student_name": new_name,
                    "new_father_name": new_father,
                    "new_assigned_teacher": new_teacher,
                    "new_status": new_status,
                    "notes": notes,
                },
            ),
            (
                (
                    old_name,
                    old_father,
                    old_teacher,
                    updated_record,
                ),
                {},
            ),
            (
                (
                    old_name,
                    old_father,
                    old_teacher,
                    new_name,
                    new_father,
                    new_teacher,
                    new_status,
                    notes,
                ),
                {},
            ),
            (
                (
                    old_name,
                    old_father,
                    new_name,
                    new_father,
                    new_teacher,
                    new_status,
                ),
                {},
            ),
        ],
    )

    return True if result is None else bool(result)


def _delete_student(
    student_name: str,
    father_name: str,
    assigned_teacher: str,
) -> bool:
    func = _find_callable(
        "delete_student",
        "delete_student_record",
        "remove_student",
    )

    if func is None:
        raise AttributeError(
            "sheets.py میں delete_student() یا اس جیسا فنکشن موجود نہیں۔"
        )

    result = _call_compatible(
        func,
        [
            (
                (),
                {
                    "student_name": student_name,
                    "father_name": father_name,
                    "assigned_teacher": assigned_teacher,
                },
            ),
            (
                (
                    student_name,
                    father_name,
                    assigned_teacher,
                ),
                {},
            ),
            (
                (
                    student_name,
                    father_name,
                ),
                {},
            ),
        ],
    )

    return True if result is None else bool(result)


def _add_log(action: str):
    func = getattr(sheets, "add_log", None)
    if not callable(func):
        return

    try:
        func(auth.current_username(), action)
    except Exception:
        pass


def _display_students_table(df: pd.DataFrame):
    if df.empty:
        info_message("کوئی طالب علم موجود نہیں۔")
        return

    preferred_columns = [
        "StudentName",
        "FatherName",
        "AssignedTeacher",
        "Status",
        "DateAdded",
        "Notes",
    ]

    columns = [column for column in preferred_columns if column in df.columns]
    if not columns:
        columns = list(df.columns)

    display_df = df[columns].rename(columns=STUDENT_COLUMN_LABELS)
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.caption(f"کل طلباء: {len(df)}")


def _render_filters(students_df: pd.DataFrame) -> pd.DataFrame:
    filtered = students_df.copy()

    c1, c2, c3 = st.columns(3)

    query = c1.text_input(
        "🔍 طالب علم یا والد کے نام سے تلاش کریں",
        key="students_search",
    ).strip()

    teacher_values = []
    if "AssignedTeacher" in students_df.columns:
        teacher_values = sorted(
            value
            for value in students_df["AssignedTeacher"]
            .astype(str)
            .str.strip()
            .unique()
            if value
        )

    selected_teacher = c2.selectbox(
        "استاد",
        ["تمام"] + teacher_values,
        key="students_teacher_filter",
    )

    status_values = []
    if "Status" in students_df.columns:
        status_values = sorted(
            value
            for value in students_df["Status"]
            .astype(str)
            .str.strip()
            .unique()
            if value
        )

    selected_status = c3.selectbox(
        "حیثیت",
        ["تمام"] + status_values,
        key="students_status_filter",
    )

    if query:
        name_series = filtered.get(
            "StudentName", pd.Series("", index=filtered.index)
        ).astype(str)
        father_series = filtered.get(
            "FatherName", pd.Series("", index=filtered.index)
        ).astype(str)

        filtered = filtered[
            name_series.str.contains(query, case=False, na=False)
            | father_series.str.contains(query, case=False, na=False)
        ]

    if selected_teacher != "تمام" and "AssignedTeacher" in filtered.columns:
        filtered = filtered[
            filtered["AssignedTeacher"].astype(str).str.strip()
            == selected_teacher
        ]

    if selected_status != "تمام" and "Status" in filtered.columns:
        filtered = filtered[
            filtered["Status"].astype(str).str.strip()
            == selected_status
        ]

    return filtered


def _render_exports(df: pd.DataFrame):
    if df.empty:
        return

    display_columns = [
        column
        for column in [
            "StudentName",
            "FatherName",
            "AssignedTeacher",
            "Status",
            "DateAdded",
            "Notes",
        ]
        if column in df.columns
    ]

    export_df = df[display_columns].rename(columns=STUDENT_COLUMN_LABELS)

    c1, c2 = st.columns(2)

    if callable(to_excel_bytes):
        try:
            excel_bytes = to_excel_bytes(export_df, sheet_name="Students")
            c1.download_button(
                "📥 ایکسل فائل ڈاؤن لوڈ کریں",
                data=excel_bytes,
                file_name="students.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                use_container_width=True,
            )
        except Exception as exc:
            c1.warning(f"ایکسل فائل تیار نہیں ہو سکی: {exc}")

    if callable(dataframe_to_pdf_bytes):
        try:
            pdf_bytes = dataframe_to_pdf_bytes(
                export_df,
                "طلباء کی فہرست",
                getattr(
                    config,
                    "APP_TITLE",
                    "مدرسہ حاضری پورٹل",
                ),
            )
            c2.download_button(
                "📄 پی ڈی ایف ڈاؤن لوڈ کریں",
                data=pdf_bytes,
                file_name="students.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as exc:
            c2.warning(f"پی ڈی ایف تیار نہیں ہو سکی: {exc}")


def _render_add_student(teachers: list[dict], students_df: pd.DataFrame):
    if not teachers:
        warning_message(
            "طالب علم شامل کرنے سے پہلے کم از کم ایک فعال استاد بنائیں۔"
        )
        return

    usernames = [record["Username"] for record in teachers]
    names = {
        record["Username"]: record["FullName"]
        for record in teachers
    }

    with st.form("add_student_form", clear_on_submit=True):
        st.subheader("➕ نیا طالب علم شامل کریں")

        c1, c2 = st.columns(2)
        student_name = c1.text_input("طالب علم کا نام")
        father_name = c2.text_input("والد کا نام")

        c1, c2 = st.columns(2)
        teacher = c1.selectbox(
            "مقرر استاد",
            usernames,
            format_func=lambda username: names.get(username, username),
        )
        status = c2.selectbox(
            "حیثیت",
            _status_options(),
            index=0,
        )

        notes = st.text_area("نوٹس", height=90)

        submitted = st.form_submit_button(
            "✅ طالب علم شامل کریں",
            use_container_width=True,
            type="primary",
        )

    if not submitted:
        return

    student_name = _clean(student_name)
    father_name = _clean(father_name)
    teacher = _clean(teacher)

    if not student_name:
        error_message("طالب علم کا نام درج کریں۔")
        return

    if not father_name:
        error_message("والد کا نام درج کریں۔")
        return

    if not teacher:
        error_message("استاد منتخب کریں۔")
        return

    if not students_df.empty:
        existing_keys = {
            _student_key(
                row.get("StudentName"),
                row.get("FatherName"),
                row.get("AssignedTeacher"),
            )
            for _, row in students_df.iterrows()
        }

        if _student_key(student_name, father_name, teacher) in existing_keys:
            warning_message(
                "یہ طالب علم اسی والد اور استاد کے ساتھ پہلے سے موجود ہے۔"
            )
            return

    try:
        success = _add_student(
            student_name,
            father_name,
            teacher,
            status,
            notes,
        )
    except Exception as exc:
        error_message(f"طالب علم شامل نہیں ہو سکا: {exc}")
        return

    if success:
        _add_log(
            f"طالب علم شامل کیا: {student_name} ولد {father_name} "
            f"— استاد {names.get(teacher, teacher)}"
        )
        success_message("طالب علم کامیابی سے شامل ہو گیا۔")
        st.rerun()
    else:
        error_message("طالب علم شامل نہیں ہو سکا۔")


def _render_edit_delete(
    teachers: list[dict],
    students_df: pd.DataFrame,
):
    if students_df.empty:
        info_message("ترمیم کے لیے کوئی طالب علم موجود نہیں۔")
        return

    required = {"StudentName", "FatherName", "AssignedTeacher"}
    if not required.issubset(students_df.columns):
        missing = required - set(students_df.columns)
        error_message(
            "طلباء کی شیٹ میں مطلوبہ کالم موجود نہیں: "
            + "، ".join(sorted(missing))
        )
        return

    working = students_df.reset_index(drop=True).copy()
    working["_label"] = working.apply(
        lambda row: (
            f"{_clean(row.get('StudentName'))} ولد "
            f"{_clean(row.get('FatherName'))} | "
            f"{_clean(row.get('AssignedTeacher'))}"
        ),
        axis=1,
    )

    selected_label = st.selectbox(
        "طالب علم منتخب کریں",
        working["_label"].tolist(),
        key="student_edit_select",
    )

    row = working[working["_label"] == selected_label].iloc[0]

    old_name = _clean(row.get("StudentName"))
    old_father = _clean(row.get("FatherName"))
    old_teacher = _clean(row.get("AssignedTeacher"))

    usernames = [record["Username"] for record in teachers]
    names = {
        record["Username"]: record["FullName"]
        for record in teachers
    }

    if old_teacher and old_teacher not in usernames:
        usernames.append(old_teacher)
        names[old_teacher] = old_teacher

    with st.form("edit_student_form"):
        st.subheader("✏️ طالب علم کی معلومات تبدیل کریں")

        c1, c2 = st.columns(2)
        new_name = c1.text_input(
            "طالب علم کا نام",
            value=old_name,
        )
        new_father = c2.text_input(
            "والد کا نام",
            value=old_father,
        )

        c1, c2 = st.columns(2)

        teacher_index = (
            usernames.index(old_teacher)
            if old_teacher in usernames
            else 0
        )

        new_teacher = c1.selectbox(
            "مقرر استاد",
            usernames,
            index=teacher_index,
            format_func=lambda username: names.get(username, username),
        )

        status_options = _status_options()
        current_status = _clean(row.get("Status")) or _active_status()
        if current_status not in status_options:
            status_options.append(current_status)

        new_status = c2.selectbox(
            "حیثیت",
            status_options,
            index=status_options.index(current_status),
        )

        notes = st.text_area(
            "نوٹس",
            value=_clean(row.get("Notes")),
            height=90,
        )

        save = st.form_submit_button(
            "💾 تبدیلیاں محفوظ کریں",
            use_container_width=True,
            type="primary",
        )

    if save:
        new_name = _clean(new_name)
        new_father = _clean(new_father)
        new_teacher = _clean(new_teacher)

        if not new_name or not new_father or not new_teacher:
            error_message("نام، والد کا نام اور استاد لازمی ہیں۔")
            return

        try:
            success = _update_student(
                old_name,
                old_father,
                old_teacher,
                new_name,
                new_father,
                new_teacher,
                new_status,
                notes,
            )
        except Exception as exc:
            error_message(f"معلومات اپ ڈیٹ نہیں ہو سکیں: {exc}")
            return

        if success:
            _add_log(
                f"طالب علم کی معلومات تبدیل کیں: "
                f"{old_name} ولد {old_father} → "
                f"{new_name} ولد {new_father}"
            )
            success_message("طالب علم کی معلومات اپ ڈیٹ ہو گئیں۔")
            st.rerun()
        else:
            error_message("طالب علم کی معلومات اپ ڈیٹ نہیں ہو سکیں۔")

    st.divider()
    st.subheader("🗑️ طالب علم حذف کریں")

    confirm_key = "student_delete_confirmation"

    if st.button(
        "🗑️ منتخب طالب علم حذف کریں",
        key="student_delete_button",
        use_container_width=True,
    ):
        st.session_state[confirm_key] = selected_label

    if st.session_state.get(confirm_key) == selected_label:
        warning_message(
            f"کیا آپ واقعی {old_name} ولد {old_father} کو حذف کرنا چاہتے ہیں؟"
        )

        yes, no = st.columns(2)

        if yes.button(
            "ہاں، حذف کریں",
            key="student_delete_yes",
            use_container_width=True,
        ):
            try:
                success = _delete_student(
                    old_name,
                    old_father,
                    old_teacher,
                )
            except Exception as exc:
                error_message(f"طالب علم حذف نہیں ہو سکا: {exc}")
                return

            if success:
                _add_log(
                    f"طالب علم حذف کیا: {old_name} ولد {old_father} "
                    f"— استاد {old_teacher}"
                )
                st.session_state.pop(confirm_key, None)
                success_message("طالب علم کامیابی سے حذف ہو گیا۔")
                st.rerun()
            else:
                error_message("طالب علم حذف نہیں ہو سکا۔")

        if no.button(
            "منسوخ کریں",
            key="student_delete_no",
            use_container_width=True,
        ):
            st.session_state.pop(confirm_key, None)
            st.rerun()


def render_students_page():
    """
    app.py اسی فنکشن کو کال کرتا ہے۔
    """
    require_login()

    if not auth.is_admin():
        error_message("یہ صفحہ صرف منتظم کے لیے مخصوص ہے۔")
        st.stop()

    st.title("🎓 طلباء کا انتظام")

    try:
        students_df = _get_all_students()
    except Exception as exc:
        error_message(f"طلباء کا ریکارڈ حاصل نہیں ہو سکا: {exc}")
        return

    teachers = _get_teacher_records()

    tabs = st.tabs(
        [
            "📋 طلباء کی فہرست",
            "➕ نیا طالب علم",
            "✏️ ترمیم یا حذف",
        ]
    )

    with tabs[0]:
        filtered = _render_filters(students_df)
        _display_students_table(filtered)
        st.divider()
        _render_exports(filtered)

    with tabs[1]:
        _render_add_student(teachers, students_df)

    with tabs[2]:
        _render_edit_delete(teachers, students_df)


# پرانے app.py یا دوسرے modules کے لیے اختیاری alias
def render_student_page():
    render_students_page()
