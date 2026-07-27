# logs.py
"""
سرگرمی لاگز کا صفحہ (Activity Logs Module)
==================================================
یہ صفحہ صرف منتظم (Admin) کے لیے مخصوص ہے۔ یہاں سسٹم میں ہونے والی ہر اہم
کارروائی (طالب علم شامل/ترمیم/حذف، حاضری جمع/ترمیم/حذف، استاد کا اضافہ/حذف،
پاس ورڈ تبدیلی وغیرہ) کا مکمل ریکارڈ دیکھا، تلاش، فلٹر اور منظم کیا جا سکتا ہے۔

اصول: اس فائل میں گوگل شیٹس کا کوئی براہِ راست لاجک نہیں لکھا گیا — ہر ڈیٹا بیس
عملیہ sheets.py کے ذریعے انجام دیا جاتا ہے۔
"""

import streamlit as st
import pandas as pd
from datetime import timedelta

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
    today_str,
    current_month_str,
)
from reports import to_excel_bytes, dataframe_to_pdf_bytes


def render_logs_page():
    require_admin()

    st.title("🧾 سرگرمی لاگز")
    st.caption("سسٹم میں ہونے والی ہر کارروائی کا مکمل اور محفوظ ریکارڈ۔")

    logs_df = build_enriched_logs_df()

    render_statistics_cards(logs_df)
    st.markdown("---")

    tabs = st.tabs(["📋 مکمل ریکارڈ اور فلٹرز", "🔍 فوری تلاش", "🗑️ لاگز کا انتظام"])

    with tabs[0]:
        render_filters_and_table(logs_df)
    with tabs[1]:
        render_instant_search(logs_df)
    with tabs[2]:
        render_maintenance_section(logs_df)


# ==================================================
# مشترکہ مددگار: لاگز کو صارف کے کردار کے ساتھ جوڑیں + قطار نمبر شامل کریں
# ==================================================
def build_enriched_logs_df() -> pd.DataFrame:
    logs_df = sheets.get_all_logs()
    if logs_df.empty:
        return logs_df

    logs_df = logs_df.reset_index(drop=True)
    logs_df["_RowNumber"] = logs_df.index + 2

    users_df = sheets.get_all_users()
    username_to_role = {}
    username_to_fullname = {}
    if not users_df.empty:
        username_to_role = dict(zip(users_df["Username"], users_df["Role"]))
        username_to_fullname = dict(zip(users_df["Username"], users_df["FullName"]))

    logs_df["Role"] = logs_df["Username"].map(username_to_role).fillna("نامعلوم")
    logs_df["FullName"] = logs_df["Username"].map(username_to_fullname).fillna(logs_df["Username"])

    def split_action(action_text):
        action_text = str(action_text)
        if ":" in action_text:
            head, tail = action_text.split(":", 1)
            return head.strip(), tail.strip()
        return action_text.strip(), ""

    split_result = logs_df["Action"].apply(split_action)
    logs_df["ActionType"] = split_result.apply(lambda x: x[0])
    logs_df["Details"] = split_result.apply(lambda x: x[1])

    return logs_df


def render_statistics_cards(logs_df: pd.DataFrame):
    total_logs = len(logs_df)
    today = today_str()
    month = current_month_str()

    todays_logs = 0
    months_logs = 0
    active_users_today = 0

    if not logs_df.empty:
        todays_logs = len(logs_df[logs_df["Date"] == today])
        months_logs = len(logs_df[logs_df["Date"].astype(str).str.startswith(month)])
        active_users_today = logs_df[logs_df["Date"] == today]["Username"].nunique()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_stat_card("کل لاگز", total_logs, "🧾")
    with col2:
        render_stat_card("آج کے لاگز", todays_logs, "📅")
    with col3:
        render_stat_card("اس مہینے کے لاگز", months_logs, "🗓️")
    with col4:
        render_stat_card("آج کے فعال صارفین", active_users_today, "👥")


DISPLAY_COLUMN_ORDER = ["Date", "Time", "Username", "Role", "ActionType", "Details"]
DISPLAY_COLUMN_LABELS = {
    "Date": "تاریخ", "Time": "وقت", "Username": "صارف",
    "Role": "کردار", "ActionType": "کارروائی", "Details": "تفصیل",
}


def display_logs_table(df: pd.DataFrame):
    if df.empty:
        info_message("کوئی لاگ ریکارڈ نہیں ملا۔")
        return
    display_df = df[DISPLAY_COLUMN_ORDER].rename(columns=DISPLAY_COLUMN_LABELS)
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.caption(f"کل ریکارڈز: {len(df)}")


def render_export_buttons(df: pd.DataFrame, filename_prefix: str):
    if df.empty:
        return
    display_df = df[DISPLAY_COLUMN_ORDER].rename(columns=DISPLAY_COLUMN_LABELS)

    col1, col2 = st.columns(2)
    with col1:
        excel_data = to_excel_bytes(display_df, sheet_name="Logs")
        st.download_button(
            "⬇️ Excel میں ایکسپورٹ کریں", data=excel_data, file_name=f"{filename_prefix}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True, key=f"excel_{filename_prefix}",
        )
    with col2:
        pdf_data = dataframe_to_pdf_bytes(display_df, "Activity Logs", "Madarsa Attendance Portal")
        st.download_button(
            "⬇️ PDF میں ایکسپورٹ کریں", data=pdf_data, file_name=f"{filename_prefix}.pdf",
            mime="application/pdf", use_container_width=True, key=f"pdf_{filename_prefix}",
        )


def render_filters_and_table(logs_df: pd.DataFrame):
    if logs_df.empty:
        info_message("ابھی تک کوئی سرگرمی لاگ موجود نہیں۔")
        return

    st.markdown("#### 🔎 فلٹرز")
    filter_mode = st.radio("تاریخ کا فلٹر", ["کوئی نہیں", "مخصوص تاریخ", "تاریخوں کی رینج"], horizontal=True, key="logs_date_mode")

    filtered = logs_df.copy()

    if filter_mode == "مخصوص تاریخ":
        selected_date = st.date_input("تاریخ منتخب کریں", value=pd.to_datetime(today_str()), key="logs_single_date")
        filtered = filtered[filtered["Date"] == str(selected_date)]
    elif filter_mode == "تاریخوں کی رینج":
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("شروع کی تاریخ", value=pd.to_datetime(today_str()) - timedelta(days=7), key="logs_range_start")
        with col2:
            end_date = st.date_input("آخری تاریخ", value=pd.to_datetime(today_str()), key="logs_range_end")
        if start_date > end_date:
            error_message("شروع کی تاریخ، آخری تاریخ سے پہلے ہونی چاہیے۔")
        else:
            filtered["_parsed_date"] = pd.to_datetime(filtered["Date"], errors="coerce")
            filtered = filtered[
                (filtered["_parsed_date"] >= pd.to_datetime(start_date))
                & (filtered["_parsed_date"] <= pd.to_datetime(end_date))
            ].drop(columns=["_parsed_date"])

    col1, col2, col3 = st.columns(3)
    with col1:
        user_options = ["تمام"] + sorted(logs_df["Username"].dropna().unique().tolist())
        user_filter = st.selectbox("صارف کے مطابق فلٹر کریں", user_options, key="logs_user_filter")
    with col2:
        role_options = ["تمام"] + sorted(logs_df["Role"].dropna().unique().tolist())
        role_filter = st.selectbox("کردار کے مطابق فلٹر کریں", role_options, key="logs_role_filter")
    with col3:
        action_options = ["تمام"] + sorted(logs_df["ActionType"].dropna().unique().tolist())
        action_filter = st.selectbox("کارروائی کے مطابق فلٹر کریں", action_options, key="logs_action_filter")

    if user_filter != "تمام":
        filtered = filtered[filtered["Username"] == user_filter]
    if role_filter != "تمام":
        filtered = filtered[filtered["Role"] == role_filter]
    if action_filter != "تمام":
        filtered = filtered[filtered["ActionType"] == action_filter]

    display_logs_table(filtered)
    render_export_buttons(filtered, "activity_logs")


def render_instant_search(logs_df: pd.DataFrame):
    if logs_df.empty:
        info_message("ابھی تک کوئی سرگرمی لاگ موجود نہیں۔")
        return

    query = st.text_input("صارف نام، پورا نام، کارروائی یا تفصیل کے مطابق تلاش کریں", key="logs_search_query")

    if not query.strip():
        info_message("تلاش کرنے کے لیے اوپر کچھ لکھیں۔")
        return

    q = query.strip()
    mask = (
        logs_df["Username"].astype(str).str.contains(q, case=False, na=False)
        | logs_df["FullName"].astype(str).str.contains(q, case=False, na=False)
        | logs_df["ActionType"].astype(str).str.contains(q, case=False, na=False)
        | logs_df["Details"].astype(str).str.contains(q, case=False, na=False)
    )
    result = logs_df[mask]

    display_logs_table(result)
    render_export_buttons(result, "logs_search_results")


def render_maintenance_section(logs_df: pd.DataFrame):
    if logs_df.empty:
        info_message("ابھی تک کوئی سرگرمی لاگ موجود نہیں۔")
        return

    sub_tabs = st.tabs(["🗑️ ایک لاگ حذف کریں", "🗂️ منتخب لاگز حذف کریں", "⚠️ تمام لاگز حذف کریں"])

    with sub_tabs[0]:
        render_delete_single_log(logs_df)
    with sub_tabs[1]:
        render_delete_selected_logs(logs_df)
    with sub_tabs[2]:
        render_delete_all_logs()


def _build_log_labels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_label"] = (
        df["Date"].astype(str) + " " + df["Time"].astype(str) + " | "
        + df["Username"].astype(str) + " | " + df["ActionType"].astype(str)
    )
    return df


def render_delete_single_log(logs_df: pd.DataFrame):
    st.markdown("ایک مخصوص لاگ اندراج منتخب کر کے حذف کریں۔")
    labeled_df = _build_log_labels(logs_df)
    selected_label = st.selectbox("لاگ منتخب کریں", labeled_df["_label"].tolist(), key="delete_single_select")
    selected_row = labeled_df[labeled_df["_label"] == selected_label].iloc[0]

    confirm_key = "confirm_delete_single_log"
    if st.button("🗑️ یہ لاگ حذف کریں", key="delete_single_btn", use_container_width=True):
        st.session_state[confirm_key] = selected_label

    if st.session_state.get(confirm_key) == selected_label:
        warning_message(f"کیا آپ واقعی یہ لاگ حذف کرنا چاہتے ہیں؟\n\n{selected_label}")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ ہاں، حذف کریں", key="confirm_single_yes", use_container_width=True):
                success = sheets.delete_log_row(int(selected_row["_RowNumber"]))
                if success:
                    sheets.add_log(
                        auth.current_username(),
                        f"ایک لاگ اندراج حذف کیا: {selected_row['Username']} - {selected_row['ActionType']} ({selected_row['Date']})",
                    )
                    del st.session_state[confirm_key]
                    success_message("لاگ کامیابی سے حذف کر دیا گیا۔")
                    st.rerun()
                else:
                    error_message("لاگ حذف کرنے میں خرابی پیش آئی۔")
        with c2:
            if st.button("❌ منسوخ کریں", key="confirm_single_no", use_container_width=True):
                del st.session_state[confirm_key]
                st.rerun()


def render_delete_selected_logs(logs_df: pd.DataFrame):
    st.markdown("متعدد لاگز منتخب کر کے ایک ساتھ حذف کریں۔")
    labeled_df = _build_log_labels(logs_df)
    selected_labels = st.multiselect("لاگز منتخب کریں", labeled_df["_label"].tolist(), key="delete_multi_select")

    if not selected_labels:
        info_message("حذف کرنے کے لیے اوپر سے ایک یا زیادہ لاگز منتخب کریں۔")
        return

    confirm_key = "confirm_delete_selected_logs"
    if st.button(f"🗑️ منتخب کردہ {len(selected_labels)} لاگز حذف کریں", key="delete_multi_btn", use_container_width=True):
        st.session_state[confirm_key] = True

    if st.session_state.get(confirm_key):
        warning_message(f"کیا آپ واقعی منتخب کردہ {len(selected_labels)} لاگز حذف کرنا چاہتے ہیں؟")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ ہاں، حذف کریں", key="confirm_multi_yes", use_container_width=True):
                selected_rows = labeled_df[labeled_df["_label"].isin(selected_labels)]
                row_numbers = selected_rows["_RowNumber"].astype(int).tolist()
                success = sheets.delete_log_rows(row_numbers)
                if success:
                    sheets.add_log(auth.current_username(), f"منتخب کردہ {len(row_numbers)} لاگز حذف کیے")
                    del st.session_state[confirm_key]
                    success_message(f"{len(row_numbers)} لاگز کامیابی سے حذف کر دیے گئے۔")
                    st.rerun()
                else:
                    error_message("منتخب لاگز حذف کرنے میں خرابی پیش آئی۔")
        with c2:
            if st.button("❌ منسوخ کریں", key="confirm_multi_no", use_container_width=True):
                del st.session_state[confirm_key]
                st.rerun()


def render_delete_all_logs():
    st.markdown("⚠️ یہ عمل **تمام** سرگرمی لاگز کو مستقل طور پر حذف کر دے گا۔ یہ واپس نہیں ہو سکتا۔")

    confirm_key = "confirm_delete_all_logs"
    if st.button("⚠️ تمام لاگز حذف کریں", key="delete_all_btn", use_container_width=True):
        st.session_state[confirm_key] = True

    if st.session_state.get(confirm_key):
        warning_message("کیا آپ بالکل یقین رکھتے ہیں؟ تمام سرگرمی لاگز ہمیشہ کے لیے حذف ہو جائیں گے۔")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ ہاں، سب کچھ حذف کریں", key="confirm_all_yes", use_container_width=True):
                success = sheets.clear_all_logs()
                if success:
                    del st.session_state[confirm_key]
                    success_message("تمام لاگز کامیابی سے حذف کر دیے گئے۔")
                    st.rerun()
                else:
                    error_message("تمام لاگز حذف کرنے میں خرابی پیش آئی۔")
        with c2:
            if st.button("❌ منسوخ کریں", key="confirm_all_no", use_container_width=True):
                del st.session_state[confirm_key]
                st.rerun()