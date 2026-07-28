# reports.py
"""
رپورٹس کا ماڈیول

یہ ماڈیول منتظم کے لیے درج ذیل سہولیات فراہم کرتا ہے:
    - یومیہ، ہفتہ وار، ماہانہ اور مخصوص تاریخی رینج کی حاضری رپورٹس
    - صبح اور دوپہر کی حاضری کی الگ فلٹرنگ اور شماریات
    - روزانہ تعلیمی کام کی رپورٹ: سبق، سبقی، منزل، پاؤ اور کیفیت
    - ماہانہ غیر درج شدہ اندراجات کی رپورٹ
    - تعلیمی ایام کی گنتی، جمعہ کو خارج کرتے ہوئے
    - مہینے کے شروع اور آخر کا سبق اور ماہانہ سبق کی پیش رفت
    - Excel اور PDF ایکسپورٹ

اہم اصول:
    - Google Sheets کے تمام عملیات صرف sheets.py کے ذریعے ہوتے ہیں۔
    - RollNumber استعمال نہیں ہوتا۔
    - طالب علم کی بنیادی شناخت StudentName + FatherName ہے۔
    - طالب علم کو استاد کے ساتھ جوڑنے کے لیے AssignedTeacher استعمال ہوتا ہے۔
    - to_excel_bytes() اور dataframe_to_pdf_bytes() عوامی فنکشنز ہیں۔
"""

from __future__ import annotations

import io
import os
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Iterable
from xml.sax.saxutils import escape

import pandas as pd
import plotly.express as px
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import config
import sheets
import auth

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:
    arabic_reshaper = None
    get_display = None
from utils import (
    error_message,
    info_message,
    render_stat_card,
    require_admin,
    today_str,
)



PDF_URDU_FONT_NAME = "UrduReportFont"

# Known teacher usernames mapped to their Urdu display names.
# This fallback is used even if the Users sheet contains an English name.
TEACHER_URDU_FALLBACK = {
    "amir": "قاری عامر",
    "ifrahim": "قاری افراہیم",
    "ibrahim": "قاری افراہیم",
    "anas": "قاری انس",
    "khuzaima": "قاری خزیمہ",
}


def _urdu_font_candidates() -> list[str]:
    """
    Urdu PDF کے لیے ممکنہ font paths ترجیحی ترتیب میں واپس کریں۔

    Project کے اندر موجود Noto Nastaliq/Naskh font پہلے استعمال ہوگا،
    پھر Windows/Linux کے معروف Urdu-capable fonts آزمائے جائیں گے۔
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))

    return [
        os.environ.get("URDU_PDF_FONT_PATH", ""),
        os.path.join(
            base_dir,
            "assets",
            "fonts",
            "NotoNaskhArabic-Regular.ttf",
        ),
        os.path.join(
            base_dir,
            "assets",
            "fonts",
            "NotoNastaliqUrdu-Regular.ttf",
        ),
        r"C:\Windows\Fonts\Nirmala.ttf",
        r"C:\Windows\Fonts\NirmalaB.ttf",
        r"C:\Windows\Fonts\NirmalaS.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoNastaliqUrdu-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoNastaliqUrdu-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


def _find_urdu_font_path() -> str | None:
    """پہلا موجود Urdu-capable font path واپس کریں۔"""
    for candidate in _urdu_font_candidates():
        if candidate and os.path.isfile(candidate):
            return candidate

    return None


def _register_urdu_pdf_font() -> str:
    """
    دستیاب fonts کو ایک ایک کرکے آزمائیں اور پہلا کامیاب font register کریں۔

    اہم اصلاح:
    پہلے code میں اگر project font موجود مگر خراب/unsupported ہوتا تو code
    فوراً Helvetica پر چلا جاتا تھا۔ Helvetica اردو glyphs نہیں دکھاتا،
    اسی لیے PDF میں صرف نقطے اور علامات نظر آ رہی تھیں۔
    """
    if PDF_URDU_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return PDF_URDU_FONT_NAME

    attempted_paths = []

    for font_path in _urdu_font_candidates():
        if not font_path or not os.path.isfile(font_path):
            continue

        attempted_paths.append(font_path)

        try:
            pdfmetrics.registerFont(
                TTFont(PDF_URDU_FONT_NAME, font_path)
            )
            return PDF_URDU_FONT_NAME
        except Exception:
            # اگلا موجود font آزمائیں؛ خاموشی سے Helvetica استعمال نہ کریں۔
            continue

    expected_project_font = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "assets",
        "fonts",
        "NotoNaskhArabic-Regular.ttf",
    )

    raise RuntimeError(
        "Urdu PDF font register نہیں ہو سکا۔ "
        "براہ کرم یہ font file درست جگہ رکھیں: "
        f"{expected_project_font}. "
        "آزمائے گئے fonts: "
        + (", ".join(attempted_paths) if attempted_paths else "کوئی نہیں")
    )


def _validate_urdu_pdf_support() -> None:
    """PDF بنانے سے پہلے Urdu packages اور font کی موجودگی چیک کریں۔"""
    missing_packages = []

    if arabic_reshaper is None:
        missing_packages.append("arabic-reshaper")

    if get_display is None:
        missing_packages.append("python-bidi")

    if missing_packages:
        raise RuntimeError(
            "Urdu PDF کے لیے یہ packages install کریں: "
            + ", ".join(missing_packages)
        )

    _register_urdu_pdf_font()


def _contains_urdu(value: str) -> bool:
    return any(
        "\u0600" <= char <= "\u06ff"
        or "\u0750" <= char <= "\u077f"
        or "\u08a0" <= char <= "\u08ff"
        for char in value
    )


def _pdf_text(value) -> str:
    """
    اردو/عربی متن کو ReportLab کے لیے صحیح جوڑی ہوئی اور RTL شکل میں بدلیں۔
    """
    cleaned = _clean(value)

    if not cleaned or not _contains_urdu(cleaned):
        return cleaned

    if arabic_reshaper is None or get_display is None:
        return cleaned

    try:
        return get_display(arabic_reshaper.reshape(cleaned))
    except Exception:
        return cleaned


def _pdf_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame کے headers اور تمام cells کو PDF کے لیے reshape کریں۔"""
    prepared = df.copy().fillna("").astype(str)
    prepared.columns = [_pdf_text(column) for column in prepared.columns]

    for column in prepared.columns:
        prepared[column] = prepared[column].map(_pdf_text)

    return prepared


def _pdf_paragraph(text, style):
    """اردو متن کے لیے محفوظ right-aligned ReportLab Paragraph بنائیں۔"""
    cleaned = _clean(text)
    style_copy = style.clone(
        f"urdu_{id(style)}_{abs(hash(cleaned))}"
    )
    style_copy.fontName = _register_urdu_pdf_font()
    style_copy.alignment = (
        2 if _contains_urdu(cleaned) else style.alignment
    )
    style_copy.leading = max(
        getattr(style_copy, "leading", 0),
        12,
    )
    return Paragraph(
        escape(_pdf_text(cleaned)),
        style_copy,
    )


def to_excel_bytes(
    df: pd.DataFrame,
    sheet_name: str = "Report",
) -> bytes:
    output = io.BytesIO()
    safe_sheet_name = (sheet_name or "Report")[:31]

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(
            writer,
            index=False,
            sheet_name=safe_sheet_name,
        )

    return output.getvalue()


def dataframe_to_pdf_bytes(
    df: pd.DataFrame,
    title: str = "رپورٹ",
    subtitle: str = "",
) -> bytes:
    _validate_urdu_pdf_support()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
    )

    styles = getSampleStyleSheet()
    font_name = _register_urdu_pdf_font()
    elements = [_pdf_paragraph(title, styles["Title"])]

    if subtitle:
        elements.append(_pdf_paragraph(subtitle, styles["Normal"]))

    elements.append(Spacer(1, 8))

    if df.empty:
        elements.append(
            _pdf_paragraph("کوئی ریکارڈ موجود نہیں۔", styles["Normal"])
        )
    else:
        safe_df = _pdf_dataframe(df)
        safe_df = safe_df.apply(
            lambda column: column.map(
                lambda value: (
                    value[:30] + "..."
                    if len(value) > 33
                    else value
                )
            )
        )

        table_data = [
            [str(column) for column in safe_df.columns]
        ] + safe_df.values.tolist()

        page_width = landscape(A4)[0] - (24 * mm)
        column_count = max(len(safe_df.columns), 1)
        column_width = page_width / column_count

        table = Table(
            table_data,
            repeatRows=1,
            colWidths=[column_width] * column_count,
        )

        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor(config.COLOR_PRIMARY),
                    ),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f2f2f2")],
                    ),
                ]
            )
        )
        elements.append(table)

    document.build(elements)
    return buffer.getvalue()


ATTENDANCE_COLUMN_LABELS = {
    "Date": "تاریخ",
    "AttendanceSession": "حاضری کا وقت",
    "StudentName": "طالب علم کا نام",
    "FatherName": "والد کا نام",
    "TeacherUsername": "استاد کا یوزرنیم",
    "TeacherName": "استاد",
    "Status": "حیثیت",
    "TimeSubmitted": "جمع کروانے کا وقت",
}

DAILY_WORK_COLUMN_LABELS = {
    "Date": "تاریخ",
    "StudentName": "طالب علم کا نام",
    "FatherName": "والد کا نام",
    "TeacherUsername": "استاد کا یوزرنیم",
    "TeacherName": "استاد",
    "SabaqSurah": "سبق کی سورت",
    "SabaqAyah": "سبق کی آیت",
    "SabqiSurah": "سبقی کی سورت",
    "SabqiAyah": "سبقی کی آیت",
    "ManzilJuz": "منزل کا پارہ",
    "ManzilAmount": "منزل کی مقدار",
    "ManzilHalf": "منزل کا نصف",
    "PaoJuz": "پاؤ کا پارہ",
    "PaoQuarter": "پاؤ نمبر",
    "Remarks": "کیفیت",
    "TimeSubmitted": "جمع کروانے کا وقت",
}


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalise(value) -> str:
    return _clean(value).casefold()



@st.cache_data(ttl=60, show_spinner=False)
def _teacher_display_map() -> dict[str, str]:
    """Users sheet سے teacher username کو مکمل Urdu نام میں بدلنے کا نقشہ۔"""
    users = sheets.get_all_users()

    if users is None or users.empty:
        return {}

    mapping: dict[str, str] = {}

    for _, row in users.iterrows():
        if _normalise(row.get("Role")) != _normalise(config.ROLE_TEACHER):
            continue

        username = _clean(row.get("Username"))
        full_name = _clean(row.get("FullName")) or username

        if username:
            mapping[_normalise(username)] = full_name
        if full_name:
            mapping[_normalise(full_name)] = full_name

    return mapping


def _teacher_display_name(value) -> str:
    """Teacher username/name کو قابلِ اعتماد اردو نام میں بدلیں۔"""
    cleaned = _clean(value)
    if not cleaned:
        return ""

    normalised = _normalise(cleaned)

    # پہلے معروف usernames کے مستقل اردو نام استعمال کریں۔
    if normalised in TEACHER_URDU_FALLBACK:
        return TEACHER_URDU_FALLBACK[normalised]

    # پھر Users sheet کا FullName استعمال کریں۔
    mapped_name = _teacher_display_map().get(normalised, cleaned)

    # اگر Users sheet نے دوبارہ username ہی واپس کیا ہو تو fallback لگائیں۔
    return TEACHER_URDU_FALLBACK.get(
        _normalise(mapped_name),
        mapped_name,
    )


def _prepare_dataframe(
    df: pd.DataFrame | None,
    headers: list[str],
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=headers)

    prepared = df.copy()

    for column in headers:
        if column not in prepared.columns:
            prepared[column] = ""

    prepared = prepared[headers].copy()

    for column in headers:
        prepared[column] = (
            prepared[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    return prepared


def _prepare_attendance_dataframe(
    df: pd.DataFrame | None,
) -> pd.DataFrame:
    prepared = _prepare_dataframe(df, config.ATTENDANCE_HEADERS)

    if not prepared.empty and "TeacherName" in prepared.columns:
        prepared["TeacherName"] = prepared["TeacherName"].map(
            _teacher_display_name
        )

    return prepared


def _prepare_daily_work_dataframe(
    df: pd.DataFrame | None,
) -> pd.DataFrame:
    prepared = _prepare_dataframe(df, config.DAILY_WORK_HEADERS)

    if not prepared.empty and "TeacherName" in prepared.columns:
        prepared["TeacherName"] = prepared["TeacherName"].map(
            _teacher_display_name
        )

    return prepared


def _prepare_students_dataframe(
    df: pd.DataFrame | None,
) -> pd.DataFrame:
    return _prepare_dataframe(df, config.STUDENTS_HEADERS)


def _student_label(student_name: str, father_name: str) -> str:
    name = _clean(student_name)
    father = _clean(father_name)
    return f"{name} — والد: {father}" if father else name


def _month_dates(month: str) -> list[date]:
    year, month_number = map(int, month.split("-"))
    total_days = monthrange(year, month_number)[1]
    return [
        date(year, month_number, day)
        for day in range(1, total_days + 1)
    ]


def _educational_dates(
    month: str,
    up_to_today: bool = True,
) -> list[date]:
    dates = [
        item
        for item in _month_dates(month)
        if item.weekday() != config.FRIDAY_WEEKDAY
    ]

    if up_to_today:
        today = datetime.strptime(
            today_str(),
            config.DATE_FORMAT,
        ).date()
        dates = [item for item in dates if item <= today]

    return dates


def _valid_month(month: str) -> bool:
    try:
        datetime.strptime(f"{month}-01", "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def _active_students() -> pd.DataFrame:
    students = _prepare_students_dataframe(
        sheets.get_all_students()
    )

    if students.empty:
        return students

    return students[
        students["Status"] == config.STUDENT_STATUS_ACTIVE
    ].copy()


def _apply_attendance_filters(
    df: pd.DataFrame,
    key_prefix: str,
) -> pd.DataFrame:
    if df.empty:
        return df

    filtered = df.copy()
    filtered["_StudentLabel"] = filtered.apply(
        lambda row: _student_label(
            row.get("StudentName"),
            row.get("FatherName"),
        ),
        axis=1,
    )

    students = sorted(
        value
        for value in filtered["_StudentLabel"].unique()
        if _clean(value)
    )
    teachers = sorted(
        value
        for value in filtered["TeacherName"].unique()
        if _clean(value)
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        selected_student = st.selectbox(
            "طالب علم",
            ["تمام"] + students,
            key=f"{key_prefix}_student",
        )

    with col2:
        selected_teacher = st.selectbox(
            "استاد",
            ["تمام"] + teachers,
            key=f"{key_prefix}_teacher",
        )

    with col3:
        selected_session = st.selectbox(
            "حاضری کا وقت",
            ["تمام"] + list(config.ATTENDANCE_SESSIONS),
            key=f"{key_prefix}_session",
        )

    with col4:
        selected_status = st.selectbox(
            "حیثیت",
            ["تمام"] + list(config.ATTENDANCE_STATUSES),
            key=f"{key_prefix}_status",
        )

    if selected_student != "تمام":
        filtered = filtered[
            filtered["_StudentLabel"] == selected_student
        ]

    if selected_teacher != "تمام":
        filtered = filtered[
            filtered["TeacherName"] == selected_teacher
        ]

    if selected_session != "تمام":
        filtered = filtered[
            filtered["AttendanceSession"] == selected_session
        ]

    if selected_status != "تمام":
        filtered = filtered[
            filtered["Status"] == selected_status
        ]

    return filtered.drop(columns=["_StudentLabel"], errors="ignore")


def _apply_daily_work_filters(
    df: pd.DataFrame,
    key_prefix: str,
) -> pd.DataFrame:
    if df.empty:
        return df

    filtered = df.copy()
    filtered["_StudentLabel"] = filtered.apply(
        lambda row: _student_label(
            row.get("StudentName"),
            row.get("FatherName"),
        ),
        axis=1,
    )

    students = sorted(
        value
        for value in filtered["_StudentLabel"].unique()
        if _clean(value)
    )
    teachers = sorted(
        value
        for value in filtered["TeacherName"].unique()
        if _clean(value)
    )

    col1, col2 = st.columns(2)

    with col1:
        selected_student = st.selectbox(
            "طالب علم",
            ["تمام"] + students,
            key=f"{key_prefix}_work_student",
        )

    with col2:
        selected_teacher = st.selectbox(
            "استاد",
            ["تمام"] + teachers,
            key=f"{key_prefix}_work_teacher",
        )

    if selected_student != "تمام":
        filtered = filtered[
            filtered["_StudentLabel"] == selected_student
        ]

    if selected_teacher != "تمام":
        filtered = filtered[
            filtered["TeacherName"] == selected_teacher
        ]

    return filtered.drop(columns=["_StudentLabel"], errors="ignore")


def render_attendance_stats(df: pd.DataFrame) -> None:
    total = len(df)
    present = len(df[df["Status"] == config.STATUS_PRESENT])
    absent = len(df[df["Status"] == config.STATUS_ABSENT])
    late = len(df[df["Status"] == config.STATUS_LATE])
    leave = len(df[df["Status"] == config.STATUS_LEAVE])

    percentage = (
        round(((present + late) / total) * 100, 1)
        if total
        else 0
    )

    columns = st.columns(6)

    with columns[0]:
        render_stat_card("کل ریکارڈز", total, "📋")
    with columns[1]:
        render_stat_card("حاضر", present, "✅")
    with columns[2]:
        render_stat_card("غیر حاضر", absent, "❌")
    with columns[3]:
        render_stat_card(config.STATUS_LATE, late, "⏰")
    with columns[4]:
        render_stat_card("رخصت", leave, "📝")
    with columns[5]:
        render_stat_card("حاضری کی شرح", f"{percentage}%", "📈")


def _render_export_buttons(
    display_df: pd.DataFrame,
    filename_prefix: str,
    pdf_title: str,
    pdf_subtitle: str = "",
) -> None:
    col1, col2 = st.columns(2)

    with col1:
        st.download_button(
            "⬇️ Excel ڈاؤن لوڈ کریں",
            data=to_excel_bytes(display_df, sheet_name="Report"),
            file_name=f"{filename_prefix}.xlsx",
            mime=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            ),
            use_container_width=True,
            key=f"excel_{filename_prefix}",
        )

    with col2:
        st.download_button(
            "⬇️ PDF ڈاؤن لوڈ کریں",
            data=dataframe_to_pdf_bytes(
                display_df,
                pdf_title,
                pdf_subtitle,
            ),
            file_name=f"{filename_prefix}.pdf",
            mime="application/pdf",
            use_container_width=True,
            key=f"pdf_{filename_prefix}",
        )


def render_attendance_table_and_export(
    df: pd.DataFrame,
    filename_prefix: str,
    pdf_title: str,
    pdf_subtitle: str = "",
) -> None:
    if df.empty:
        info_message(
            "منتخب فلٹرز کے مطابق کوئی حاضری ریکارڈ نہیں ملا۔"
        )
        return

    display_df = (
        df[config.ATTENDANCE_HEADERS]
        .copy()
        .rename(columns=ATTENDANCE_COLUMN_LABELS)
    )

    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.caption(f"کل ریکارڈز: {len(display_df)}")

    _render_export_buttons(
        display_df,
        filename_prefix,
        pdf_title,
        pdf_subtitle,
    )


def render_daily_work_table_and_export(
    df: pd.DataFrame,
    filename_prefix: str,
    pdf_title: str,
    pdf_subtitle: str = "",
) -> None:
    if df.empty:
        info_message(
            "منتخب فلٹرز کے مطابق کوئی تعلیمی ریکارڈ نہیں ملا۔"
        )
        return

    display_df = (
        df[config.DAILY_WORK_HEADERS]
        .copy()
        .rename(columns=DAILY_WORK_COLUMN_LABELS)
    )

    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.caption(f"کل ریکارڈز: {len(display_df)}")

    _render_export_buttons(
        display_df,
        filename_prefix,
        pdf_title,
        pdf_subtitle,
    )


def render_reports_page():
    auth.require_login()

    st.title("📑 رپورٹس")

    if auth.is_teacher():
        st.caption("اپنے طلباء کی انفرادی ماہانہ رپورٹ تیار کریں")
        render_student_monthly_report(teacher_only=True)
        return

    require_admin()
    st.caption(
        "حاضری، روزانہ تعلیمی کام، ماہانہ پیش رفت اور "
        "غیر درج شدہ اندراجات کی رپورٹس"
    )

    tabs = st.tabs(
        [
            "👤 طالب علم کی ماہانہ رپورٹ",
            "📆 یومیہ رپورٹ",
            "📅 ہفتہ وار رپورٹ",
            "🗓️ ماہانہ رپورٹ",
            "📊 مخصوص تاریخی رینج",
            "📖 تعلیمی کام",
            "⚠️ غیر درج شدہ اندراجات",
            "📈 چارٹس",
        ]
    )

    with tabs[0]:
        render_student_monthly_report(teacher_only=False)
    with tabs[1]:
        render_daily_report()
    with tabs[2]:
        render_weekly_report()
    with tabs[3]:
        render_monthly_report()
    with tabs[4]:
        render_custom_range_report()
    with tabs[5]:
        render_daily_work_report()
    with tabs[6]:
        render_missing_submissions_report()
    with tabs[7]:
        render_charts_and_statistics()



def _students_for_current_teacher(students: pd.DataFrame) -> pd.DataFrame:
    """صرف موجودہ استاد کے ساتھ منسلک فعال طلباء واپس کریں۔"""
    if students.empty:
        return students

    username = _normalise(auth.current_username())
    fullname = _normalise(auth.current_fullname())
    allowed = {value for value in (username, fullname) if value}

    if not allowed:
        return students.iloc[0:0].copy()

    return students[
        students["AssignedTeacher"].map(_normalise).isin(allowed)
    ].copy()


def _one_student_records(
    df: pd.DataFrame,
    student_name: str,
    father_name: str,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    return df[
        (df["StudentName"].map(_normalise) == _normalise(student_name))
        & (df["FatherName"].map(_normalise) == _normalise(father_name))
    ].copy()



def _student_summary_progress_excel_bytes(
    overview: pd.DataFrame,
    progress: pd.DataFrame,
) -> bytes:
    """صرف مکمل خلاصہ اور ماہانہ سبق کی پیش رفت کی Excel رپورٹ بنائیں۔"""
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        overview.to_excel(writer, index=False, sheet_name="مکمل خلاصہ")
        progress.to_excel(writer, index=False, sheet_name="سبق پیش رفت")

    return output.getvalue()


def _student_remarks_display(
    work: pd.DataFrame,
) -> pd.DataFrame:
    """
    صرف تاریخ اور کیفیت/تبصرہ کی رپورٹ تیار کریں۔

    سبق، سبقی، منزل اور پاؤ کے کالم اس report میں شامل نہیں کیے جاتے۔
    """
    prepared = work.copy()

    for column in ["Date", "Remarks"]:
        if column not in prepared.columns:
            prepared[column] = ""

    remarks = prepared[["Date", "Remarks"]].copy()
    remarks["Date"] = remarks["Date"].fillna("").astype(str).str.strip()
    remarks["Remarks"] = (
        remarks["Remarks"].fillna("").astype(str).str.strip()
    )

    # صرف وہ rows دکھائیں جن میں واقعی کیفیت لکھی گئی ہو۔
    remarks = remarks[remarks["Remarks"] != ""].copy()

    return remarks.rename(
        columns={
            "Date": "تاریخ",
            "Remarks": "کیفیت",
        }
    )


def _student_summary_progress_remarks_excel_bytes(
    overview: pd.DataFrame,
    progress: pd.DataFrame,
    work: pd.DataFrame,
) -> bytes:
    """
    مکمل خلاصہ، سبق کی پیش رفت اور کیفیت کی الگ Excel رپورٹ بنائیں۔

    روزانہ تعلیمی کام کے سبق، سبقی، منزل اور پاؤ والے columns شامل نہیں ہوتے۔
    """
    output = io.BytesIO()
    remarks = _student_remarks_display(work)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        overview.to_excel(
            writer,
            index=False,
            sheet_name="مکمل خلاصہ",
        )
        progress.to_excel(
            writer,
            index=False,
            sheet_name="سبق کی پیش رفت",
        )
        remarks.to_excel(
            writer,
            index=False,
            sheet_name="کیفیت",
        )

    return output.getvalue()


def _student_summary_progress_remarks_pdf_bytes(
    student_name: str,
    father_name: str,
    teacher_name: str,
    month: str,
    overview: pd.DataFrame,
    progress: pd.DataFrame,
    work: pd.DataFrame,
) -> bytes:
    """
    مکمل خلاصہ، سبق کی پیش رفت اور کیفیت کی الگ Urdu PDF رپورٹ بنائیں۔

    روزانہ تعلیمی کام کے دوسرے fields اس PDF میں شامل نہیں ہوتے۔
    """
    _validate_urdu_pdf_support()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
    )

    styles = getSampleStyleSheet()
    page_width = landscape(A4)[0] - (20 * mm)
    remarks = _student_remarks_display(work)

    elements = [
        _pdf_paragraph(
            "مکمل خلاصہ، سبق کی پیش رفت اور کیفیت",
            styles["Title"],
        ),
        _pdf_paragraph(
            (
                f"طالب علم: {student_name} | والد: {father_name} | "
                f"استاد: {teacher_name} | مہینہ: {month}"
            ),
            styles["Normal"],
        ),
        Spacer(1, 10),
        _pdf_paragraph("مکمل خلاصہ", styles["Heading2"]),
        Spacer(1, 4),
        _pdf_table(overview, page_width),
        Spacer(1, 12),
        _pdf_paragraph("سبق کی پیش رفت", styles["Heading2"]),
        Spacer(1, 4),
        _pdf_table(progress, page_width),
        Spacer(1, 12),
        _pdf_paragraph("کیفیت", styles["Heading2"]),
        Spacer(1, 4),
        _pdf_table(remarks, page_width),
    ]

    document.build(elements)
    return buffer.getvalue()



def _student_combined_excel_bytes(
    overview: pd.DataFrame,
    attendance: pd.DataFrame,
    progress: pd.DataFrame,
    missing: pd.DataFrame,
    work: pd.DataFrame,
) -> bytes:
    """ایک طالب علم کی تمام ماہانہ معلومات ایک Excel فائل میں بنائیں۔"""
    output = io.BytesIO()

    attendance_display = (
        attendance[config.ATTENDANCE_HEADERS]
        .copy()
        .rename(columns=ATTENDANCE_COLUMN_LABELS)
        if not attendance.empty
        else pd.DataFrame(columns=ATTENDANCE_COLUMN_LABELS.values())
    )

    work_display = (
        work[config.DAILY_WORK_HEADERS]
        .copy()
        .rename(columns=DAILY_WORK_COLUMN_LABELS)
        if not work.empty
        else pd.DataFrame(columns=DAILY_WORK_COLUMN_LABELS.values())
    )

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        overview.to_excel(writer, index=False, sheet_name="خلاصہ")
        attendance_display.to_excel(writer, index=False, sheet_name="حاضری")
        progress.to_excel(writer, index=False, sheet_name="سبق پیش رفت")
        missing.to_excel(writer, index=False, sheet_name="غیر درج شدہ")
        work_display.to_excel(writer, index=False, sheet_name="تعلیمی کام")

    return output.getvalue()


def _pdf_table(df: pd.DataFrame, page_width: float) -> Table:
    safe_df = _pdf_dataframe(df)

    if safe_df.empty:
        safe_df = _pdf_dataframe(
            pd.DataFrame({"تفصیل": ["کوئی ریکارڈ موجود نہیں۔"]})
        )

    safe_df = safe_df.apply(
        lambda column: column.map(
            lambda value: value[:42] + "..." if len(value) > 45 else value
        )
    )

    table_data = [
        [str(column) for column in safe_df.columns]
    ] + safe_df.values.tolist()

    column_count = max(len(safe_df.columns), 1)
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[page_width / column_count] * column_count,
    )
    table.setStyle(
        TableStyle(
            [
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, -1),
                    _register_urdu_pdf_font(),
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor(config.COLOR_PRIMARY),
                ),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f2f2f2")],
                ),
            ]
        )
    )
    return table


def _student_summary_progress_pdf_bytes(
    student_name: str,
    father_name: str,
    teacher_name: str,
    month: str,
    overview: pd.DataFrame,
    progress: pd.DataFrame,
) -> bytes:
    """صرف پہلے اور تیسرے حصے: مکمل خلاصہ اور سبق پیش رفت کی PDF بنائیں۔"""
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
    )

    styles = getSampleStyleSheet()
    page_width = landscape(A4)[0] - (20 * mm)
    elements = [
        _pdf_paragraph("طالب علم کی مختصر ماہانہ رپورٹ", styles["Title"]),
        _pdf_paragraph(
            (
                f"طالب علم: {student_name} | والد: {father_name} | "
                f"استاد: {teacher_name} | مہینہ: {month}"
            ),
            styles["Normal"],
        ),
        Spacer(1, 10),
        _pdf_paragraph("مکمل خلاصہ", styles["Heading2"]),
        Spacer(1, 4),
        _pdf_table(overview, page_width),
        Spacer(1, 12),
        _pdf_paragraph("ماہانہ سبق کی پیش رفت", styles["Heading2"]),
        Spacer(1, 4),
        _pdf_table(progress, page_width),
    ]

    document.build(elements)
    return buffer.getvalue()


def _student_combined_pdf_bytes(
    student_name: str,
    father_name: str,
    teacher_name: str,
    month: str,
    overview: pd.DataFrame,
    attendance: pd.DataFrame,
    progress: pd.DataFrame,
    missing: pd.DataFrame,
    work: pd.DataFrame,
) -> bytes:
    """تمام ماہانہ حصے ایک ہی PDF فائل میں شامل کریں۔"""
    _validate_urdu_pdf_support()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
    )

    styles = getSampleStyleSheet()
    page_width = landscape(A4)[0] - (20 * mm)
    elements = [
        _pdf_paragraph("طالب علم کی مکمل ماہانہ رپورٹ", styles["Title"]),
        _pdf_paragraph(
            (
                f"طالب علم: {student_name} | والد: {father_name} | "
                f"استاد: {teacher_name} | مہینہ: {month}"
            ),
            styles["Normal"],
        ),
        Spacer(1, 10),
    ]

    attendance_display = (
        attendance[config.ATTENDANCE_HEADERS]
        .copy()
        .rename(columns=ATTENDANCE_COLUMN_LABELS)
        if not attendance.empty
        else pd.DataFrame()
    )
    work_display = (
        work[config.DAILY_WORK_HEADERS]
        .copy()
        .rename(columns=DAILY_WORK_COLUMN_LABELS)
        if not work.empty
        else pd.DataFrame()
    )

    sections = [
        ("مکمل خلاصہ", overview),
        ("حاضری", attendance_display),
        ("ماہانہ سبق کی پیش رفت", progress),
        ("غیر درج شدہ اندراجات", missing),
        ("روزانہ تعلیمی کام", work_display),
    ]

    for section_title, section_df in sections:
        elements.append(_pdf_paragraph(section_title, styles["Heading2"]))
        elements.append(Spacer(1, 4))
        elements.append(_pdf_table(section_df, page_width))
        elements.append(Spacer(1, 12))

    document.build(elements)
    return buffer.getvalue()



def render_student_monthly_report(
    teacher_only: bool = False,
) -> None:
    """منتظم یا استاد کے لیے ایک طالب علم کی مکمل ماہانہ رپورٹ۔"""
    _validate_urdu_pdf_support()
    try:
        _validate_urdu_pdf_support()
    except RuntimeError as error:
        error_message(str(error))
        st.info(
            "درست font رکھنے کے بعد Streamlit کو مکمل بند کرکے دوبارہ چلائیں۔"
        )
    st.subheader("👤 طالب علم کی مکمل ماہانہ رپورٹ")

    month = st.text_input(
        "مہینہ درج کریں (YYYY-MM)",
        value=today_str()[:7],
        key=(
            "teacher_student_monthly_month"
            if teacher_only
            else "admin_student_monthly_month"
        ),
    ).strip()

    if not _valid_month(month):
        error_message(
            "مہینہ درست فارمیٹ YYYY-MM میں درج کریں، مثال: 2026-07"
        )
        return

    students = _active_students()
    if teacher_only:
        students = _students_for_current_teacher(students)

    if students.empty:
        info_message(
            "آپ کے ساتھ منسلک کوئی فعال طالب علم موجود نہیں۔"
            if teacher_only
            else "کوئی فعال طالب علم موجود نہیں۔"
        )
        return

    students = students.copy()
    students["_StudentReportLabel"] = students.apply(
        lambda row: (
            f"{_student_label(row.get('StudentName'), row.get('FatherName'))}"
            f" — استاد: {_teacher_display_name(row.get('AssignedTeacher'))}"
        ),
        axis=1,
    )

    selected_label = st.selectbox(
        "طالب علم منتخب کریں",
        students["_StudentReportLabel"].tolist(),
        key=(
            "teacher_student_monthly_select"
            if teacher_only
            else "admin_student_monthly_select"
        ),
    )

    student = students[
        students["_StudentReportLabel"] == selected_label
    ].iloc[0]

    student_name = _clean(student.get("StudentName"))
    father_name = _clean(student.get("FatherName"))
    teacher_name = _teacher_display_name(
        student.get("AssignedTeacher")
    )

    attendance = _prepare_attendance_dataframe(
        sheets.get_all_attendance()
    )
    attendance = attendance[
        attendance["Date"].str.startswith(month)
    ].copy()
    attendance = _one_student_records(
        attendance,
        student_name,
        father_name,
    )

    work = _prepare_daily_work_dataframe(
        sheets.get_all_daily_work()
    )
    work = work[work["Date"].str.startswith(month)].copy()
    work = _one_student_records(work, student_name, father_name)

    educational_dates = _educational_dates(month)
    student_df = pd.DataFrame([student])

    progress = _build_monthly_progress(student_df, work)
    missing = _build_missing_report(
        student_df,
        attendance,
        work,
        educational_dates,
    )

    total_records = len(attendance)
    present = len(attendance[attendance["Status"] == config.STATUS_PRESENT])
    late = len(attendance[attendance["Status"] == config.STATUS_LATE])
    attendance_rate = (
        round(((present + late) / total_records) * 100, 1)
        if total_records
        else 0
    )

    # صبح اور دوپہر کی حقیقی غیر حاضریاں Attendance sheet سے شمار کریں۔
    morning_absents = len(
        attendance[
            (
                attendance["AttendanceSession"]
                == config.ATTENDANCE_SESSION_MORNING
            )
            & (attendance["Status"] == config.STATUS_ABSENT)
        ]
    )
    afternoon_absents = len(
        attendance[
            (
                attendance["AttendanceSession"]
                == config.ATTENDANCE_SESSION_AFTERNOON
            )
            & (attendance["Status"] == config.STATUS_ABSENT)
        ]
    )

    # سبق، سبقی اور منزل کے لیے الگ absent status موجود نہیں،
    # اس لیے تعلیمی ایام میں غیر درج شدہ دن بطور absence شمار ہوتے ہیں۔
    if missing.empty:
        sabaq_absents = 0
        sabqi_absents = 0
        manzil_absents = 0
    else:
        missing_row = missing.iloc[0]
        sabaq_absents = int(
            missing_row.get(config.REPORT_SABAQ_UNMARKED, 0) or 0
        )
        sabqi_absents = int(
            missing_row.get(config.REPORT_SABQI_UNMARKED, 0) or 0
        )
        manzil_absents = int(
            missing_row.get(config.REPORT_MANZIL_UNMARKED, 0) or 0
        )

    overview = pd.DataFrame(
        [
            {
                "طالب علم": student_name,
                "والد کا نام": father_name,
                "مقرر استاد": teacher_name,
                "مہینہ": month,
                config.REPORT_EDUCATIONAL_DAYS: len(educational_dates),
                "حاضری کے کل اندراجات": total_records,
                "تعلیمی کام کے کل اندراجات": len(work),
                "صبح کی غیر حاضریاں": morning_absents,
                "دوپہر کی غیر حاضریاں": afternoon_absents,
                "سبق کی غیر حاضریاں": sabaq_absents,
                "سبقی کی غیر حاضریاں": sabqi_absents,
                "منزل کی غیر حاضریاں": manzil_absents,
                "حاضری کی شرح": f"{attendance_rate}%",
            }
        ]
    )

    st.markdown(
        f"**طالب علم:** {student_name}  \n"
        f"**والد:** {father_name}  \n"
        f"**مقرر استاد:** {teacher_name}  \n"
        f"**مہینہ:** {month}"
    )
    st.caption(
        f"تعلیمی ایام: {len(educational_dates)} (جمعہ خارج ہے)"
    )

    st.markdown("#### مکمل خلاصہ")
    st.dataframe(overview, use_container_width=True, hide_index=True)

    st.markdown("#### حاضری")
    if attendance.empty:
        info_message("اس طالب علم کی حاضری کا کوئی ریکارڈ موجود نہیں۔")
    else:
        render_attendance_stats(attendance)
        attendance_display = (
            attendance[config.ATTENDANCE_HEADERS]
            .copy()
            .rename(columns=ATTENDANCE_COLUMN_LABELS)
        )
        st.dataframe(
            attendance_display,
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("---")
    st.markdown("#### ماہانہ سبق کی پیش رفت")
    st.dataframe(progress, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### غیر درج شدہ اندراجات")
    st.dataframe(missing, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### روزانہ تعلیمی کام")
    if work.empty:
        info_message("اس طالب علم کا کوئی تعلیمی ریکارڈ موجود نہیں۔")
    else:
        work_display = (
            work[config.DAILY_WORK_HEADERS]
            .copy()
            .rename(columns=DAILY_WORK_COLUMN_LABELS)
        )
        st.dataframe(
            work_display,
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("---")
    st.markdown("### 📥 مکمل رپورٹ ایک ہی فائل میں ڈاؤن لوڈ کریں")

    safe_name = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        student_name,
    ).strip("_") or "student"
    filename_prefix = f"complete_student_report_{safe_name}_{month}"

    col1, col2 = st.columns(2)

    with col1:
        st.download_button(
            "⬇️ مکمل Excel رپورٹ",
            data=_student_combined_excel_bytes(
                overview,
                attendance,
                progress,
                missing,
                work,
            ),
            file_name=f"{filename_prefix}.xlsx",
            mime=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            ),
            use_container_width=True,
            key=f"combined_excel_{safe_name}_{month}",
        )

    with col2:
        st.download_button(
            "⬇️ مکمل PDF رپورٹ",
            data=_student_combined_pdf_bytes(
                student_name,
                father_name,
                teacher_name,
                month,
                overview,
                attendance,
                progress,
                missing,
                work,
            ),
            file_name=f"{filename_prefix}.pdf",
            mime="application/pdf",
            use_container_width=True,
            key=f"combined_pdf_{safe_name}_{month}",
        )

    st.markdown("---")
    st.markdown("### 📥 صرف خلاصہ اور سبق کی پیش رفت ڈاؤن لوڈ کریں")
    st.caption(
        "اس اختیار میں صرف پہلا حصہ (مکمل خلاصہ) اور "
        "تیسرا حصہ (ماہانہ سبق کی پیش رفت) شامل ہوں گے۔"
    )

    short_filename_prefix = (
        f"summary_and_progress_{safe_name}_{month}"
    )
    short_col1, short_col2 = st.columns(2)

    with short_col1:
        st.download_button(
            "⬇️ خلاصہ اور پیش رفت Excel",
            data=_student_summary_progress_excel_bytes(
                overview,
                progress,
            ),
            file_name=f"{short_filename_prefix}.xlsx",
            mime=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            ),
            use_container_width=True,
            key=f"summary_progress_excel_{safe_name}_{month}",
        )

    with short_col2:
        st.download_button(
            "⬇️ خلاصہ اور پیش رفت PDF",
            data=_student_summary_progress_pdf_bytes(
                student_name,
                father_name,
                teacher_name,
                month,
                overview,
                progress,
            ),
            file_name=f"{short_filename_prefix}.pdf",
            mime="application/pdf",
            use_container_width=True,
            key=f"summary_progress_pdf_{safe_name}_{month}",
        )


    st.markdown("---")
    st.markdown(
        "### 📥 مکمل خلاصہ، سبق کی پیش رفت اور کیفیت الگ ڈاؤن لوڈ کریں"
    )
    st.caption(
        "اس الگ رپورٹ میں صرف مکمل خلاصہ، سبق کی پیش رفت اور کیفیت شامل ہیں۔ "
        "سبق، سبقی، منزل، پاؤ اور روزانہ تعلیمی کام کی تفصیل شامل نہیں ہوگی۔"
    )

    summary_progress_remarks_prefix = (
        f"summary_progress_remarks_{safe_name}_{month}"
    )
    remarks_col1, remarks_col2 = st.columns(2)

    with remarks_col1:
        st.download_button(
            "⬇️ خلاصہ، سبق کی پیش رفت اور کیفیت Excel",
            data=_student_summary_progress_remarks_excel_bytes(
                overview,
                progress,
                work,
            ),
            file_name=(
                f"{summary_progress_remarks_prefix}.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            ),
            use_container_width=True,
            key=(
                f"summary_progress_remarks_excel_"
                f"{safe_name}_{month}"
            ),
        )

    with remarks_col2:
        st.download_button(
            "⬇️ خلاصہ، سبق کی پیش رفت اور کیفیت PDF",
            data=_student_summary_progress_remarks_pdf_bytes(
                student_name,
                father_name,
                teacher_name,
                month,
                overview,
                progress,
                work,
            ),
            file_name=(
                f"{summary_progress_remarks_prefix}.pdf"
            ),
            mime="application/pdf",
            use_container_width=True,
            key=(
                f"summary_progress_remarks_pdf_"
                f"{safe_name}_{month}"
            ),
        )


def render_daily_report():
    st.subheader("📆 یومیہ حاضری رپورٹ")

    selected_date = st.date_input(
        "تاریخ منتخب کریں",
        value=pd.to_datetime(today_str()).date(),
        key="daily_report_date",
    )

    attendance = _prepare_attendance_dataframe(
        sheets.get_all_attendance()
    )

    daily = attendance[
        attendance["Date"] == str(selected_date)
    ].copy()

    if daily.empty:
        info_message(
            "منتخب تاریخ کے لیے کوئی حاضری ریکارڈ موجود نہیں۔"
        )
        return

    daily = _apply_attendance_filters(daily, "daily_report")
    render_attendance_stats(daily)
    render_attendance_table_and_export(
        daily,
        f"daily_attendance_{selected_date}",
        "Daily Attendance Report",
        str(selected_date),
    )


def render_weekly_report():
    st.subheader("📅 ہفتہ وار حاضری رپورٹ")

    week_end = st.date_input(
        "ہفتے کی آخری تاریخ منتخب کریں",
        value=pd.to_datetime(today_str()).date(),
        key="weekly_report_end",
    )

    week_start = week_end - timedelta(days=6)
    st.caption(f"رینج: {week_start} تا {week_end}")

    attendance = _prepare_attendance_dataframe(
        sheets.get_all_attendance()
    )
    attendance["_ParsedDate"] = pd.to_datetime(
        attendance["Date"],
        errors="coerce",
    )

    weekly = attendance[
        (attendance["_ParsedDate"] >= pd.Timestamp(week_start))
        & (attendance["_ParsedDate"] <= pd.Timestamp(week_end))
    ].copy()

    weekly = weekly.drop(columns=["_ParsedDate"], errors="ignore")

    if weekly.empty:
        info_message(
            "منتخب ہفتے کے لیے کوئی حاضری ریکارڈ موجود نہیں۔"
        )
        return

    weekly = _apply_attendance_filters(weekly, "weekly_report")
    render_attendance_stats(weekly)
    render_attendance_table_and_export(
        weekly,
        f"weekly_attendance_{week_start}_to_{week_end}",
        "Weekly Attendance Report",
        f"{week_start} to {week_end}",
    )


def _lesson_text(surah, ayah) -> str:
    surah_text = _clean(surah)
    ayah_text = _clean(ayah)

    if surah_text and ayah_text:
        return f"{surah_text}، آیت {ayah_text}"
    if surah_text:
        return surah_text
    if ayah_text:
        return f"آیت {ayah_text}"
    return ""


def _build_monthly_progress(
    students: pd.DataFrame,
    monthly_work: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, student in students.iterrows():
        student_name = _clean(student.get("StudentName"))
        father_name = _clean(student.get("FatherName"))
        assigned_teacher = _teacher_display_name(
            student.get("AssignedTeacher")
        )

        student_work = monthly_work[
            (
                monthly_work["StudentName"].map(_normalise)
                == _normalise(student_name)
            )
            & (
                monthly_work["FatherName"].map(_normalise)
                == _normalise(father_name)
            )
        ].copy()

        student_work["_ParsedDate"] = pd.to_datetime(
            student_work["Date"],
            errors="coerce",
        )
        student_work = student_work.sort_values(
            by=["_ParsedDate", "TimeSubmitted"],
        )

        lesson_rows = student_work[
            (student_work["SabaqSurah"].str.strip() != "")
            | (student_work["SabaqAyah"].str.strip() != "")
        ]

        if lesson_rows.empty:
            starting_lesson = ""
            ending_lesson = ""
            progress_text = ""
        else:
            first_row = lesson_rows.iloc[0]
            last_row = lesson_rows.iloc[-1]

            starting_lesson = _lesson_text(
                first_row.get("SabaqSurah"),
                first_row.get("SabaqAyah"),
            )
            ending_lesson = _lesson_text(
                last_row.get("SabaqSurah"),
                last_row.get("SabaqAyah"),
            )

            progress_text = (
                f"{starting_lesson} سے {ending_lesson} تک"
                if starting_lesson and ending_lesson
                else (ending_lesson or starting_lesson)
            )

        rows.append(
            {
                "طالب علم": student_name,
                "والد کا نام": father_name,
                "مقرر استاد": assigned_teacher,
                config.REPORT_STARTING_SABAQ: starting_lesson,
                config.REPORT_ENDING_SABAQ: ending_lesson,
                config.REPORT_MONTHLY_SABAQ_PROGRESS: progress_text,
                "سبق کے درج شدہ دن": len(lesson_rows),
            }
        )

    return pd.DataFrame(rows)


def render_monthly_report():
    st.subheader("🗓️ ماہانہ جامع رپورٹ")

    month = st.text_input(
        "مہینہ درج کریں (YYYY-MM)",
        value=today_str()[:7],
        key="monthly_report_month",
    ).strip()

    if not _valid_month(month):
        error_message(
            "مہینہ درست فارمیٹ YYYY-MM میں درج کریں، مثال: 2026-07"
        )
        return

    educational_days = len(_educational_dates(month))
    attendance = _prepare_attendance_dataframe(
        sheets.get_all_attendance()
    )
    monthly_attendance = attendance[
        attendance["Date"].str.startswith(month)
    ].copy()

    work = _prepare_daily_work_dataframe(
        sheets.get_all_daily_work()
    )
    monthly_work = work[
        work["Date"].str.startswith(month)
    ].copy()

    students = _active_students()

    summary_columns = st.columns(4)

    with summary_columns[0]:
        render_stat_card(
            config.REPORT_EDUCATIONAL_DAYS,
            educational_days,
            "📚",
        )
    with summary_columns[1]:
        render_stat_card("فعال طلباء", len(students), "🎓")
    with summary_columns[2]:
        render_stat_card(
            "حاضری کے کل اندراجات",
            len(monthly_attendance),
            "📋",
        )
    with summary_columns[3]:
        render_stat_card(
            "تعلیمی کام کے اندراجات",
            len(monthly_work),
            "📖",
        )

    st.markdown("#### حاضری کی تفصیل")

    if monthly_attendance.empty:
        info_message(
            "اس مہینے کے لیے کوئی حاضری ریکارڈ موجود نہیں۔"
        )
    else:
        filtered = _apply_attendance_filters(
            monthly_attendance,
            "monthly_attendance",
        )
        render_attendance_stats(filtered)
        render_attendance_table_and_export(
            filtered,
            f"monthly_attendance_{month}",
            "Monthly Attendance Report",
            month,
        )

    st.markdown("---")
    st.markdown("#### طالب علم کے حساب سے ماہانہ سبق کی پیش رفت")

    progress = _build_monthly_progress(students, monthly_work)

    if progress.empty:
        info_message(
            "ماہانہ سبق کی پیش رفت کے لیے کوئی ریکارڈ موجود نہیں۔"
        )
        return

    st.dataframe(progress, use_container_width=True, hide_index=True)
    _render_export_buttons(
        progress,
        f"monthly_sabaq_progress_{month}",
        "Monthly Sabaq Progress",
        month,
    )


def render_custom_range_report():
    st.subheader("📊 مخصوص تاریخی رینج کی رپورٹ")

    col1, col2 = st.columns(2)

    with col1:
        start_date = st.date_input(
            "شروع کی تاریخ",
            value=(
                pd.to_datetime(today_str()).date()
                - timedelta(days=30)
            ),
            key="custom_report_start",
        )

    with col2:
        end_date = st.date_input(
            "آخری تاریخ",
            value=pd.to_datetime(today_str()).date(),
            key="custom_report_end",
        )

    if start_date > end_date:
        error_message(
            "شروع کی تاریخ آخری تاریخ سے پہلے ہونی چاہیے۔"
        )
        return

    attendance = _prepare_attendance_dataframe(
        sheets.get_all_attendance()
    )
    attendance["_ParsedDate"] = pd.to_datetime(
        attendance["Date"],
        errors="coerce",
    )

    selected = attendance[
        (attendance["_ParsedDate"] >= pd.Timestamp(start_date))
        & (attendance["_ParsedDate"] <= pd.Timestamp(end_date))
    ].copy()

    selected = selected.drop(columns=["_ParsedDate"], errors="ignore")

    if selected.empty:
        info_message(
            "منتخب تاریخی رینج کے لیے کوئی حاضری ریکارڈ موجود نہیں۔"
        )
        return

    selected = _apply_attendance_filters(selected, "custom_report")
    render_attendance_stats(selected)
    render_attendance_table_and_export(
        selected,
        f"attendance_{start_date}_to_{end_date}",
        "Custom Range Attendance Report",
        f"{start_date} to {end_date}",
    )


def render_daily_work_report():
    st.subheader("📖 روزانہ تعلیمی کام کی رپورٹ")

    col1, col2 = st.columns(2)

    with col1:
        start_date = st.date_input(
            "شروع کی تاریخ",
            value=(
                pd.to_datetime(today_str()).date()
                - timedelta(days=30)
            ),
            key="work_report_start",
        )

    with col2:
        end_date = st.date_input(
            "آخری تاریخ",
            value=pd.to_datetime(today_str()).date(),
            key="work_report_end",
        )

    if start_date > end_date:
        error_message(
            "شروع کی تاریخ آخری تاریخ سے پہلے ہونی چاہیے۔"
        )
        return

    work = _prepare_daily_work_dataframe(
        sheets.get_all_daily_work()
    )
    work["_ParsedDate"] = pd.to_datetime(
        work["Date"],
        errors="coerce",
    )

    selected = work[
        (work["_ParsedDate"] >= pd.Timestamp(start_date))
        & (work["_ParsedDate"] <= pd.Timestamp(end_date))
    ].copy()

    selected = selected.drop(columns=["_ParsedDate"], errors="ignore")

    if selected.empty:
        info_message(
            "منتخب تاریخی رینج میں کوئی تعلیمی ریکارڈ موجود نہیں۔"
        )
        return

    selected = _apply_daily_work_filters(
        selected,
        "daily_work_report",
    )

    render_daily_work_table_and_export(
        selected,
        f"daily_work_{start_date}_to_{end_date}",
        "Daily Educational Work Report",
        f"{start_date} to {end_date}",
    )


def _work_present(row: pd.Series, work_type: str) -> bool:
    if work_type == config.WORK_SABAQ:
        return bool(
            _clean(row.get("SabaqSurah"))
            or _clean(row.get("SabaqAyah"))
        )

    if work_type == config.WORK_SABQI:
        return bool(
            _clean(row.get("SabqiSurah"))
            or _clean(row.get("SabqiAyah"))
        )

    if work_type == config.WORK_MANZIL:
        return bool(_clean(row.get("ManzilJuz")))

    if work_type == config.WORK_PAO:
        return bool(_clean(row.get("PaoJuz")))

    return False


def _build_missing_report(
    students: pd.DataFrame,
    attendance: pd.DataFrame,
    work: pd.DataFrame,
    educational_dates: Iterable[date],
) -> pd.DataFrame:
    rows = []
    date_strings = [
        item.strftime(config.DATE_FORMAT)
        for item in educational_dates
    ]

    for _, student in students.iterrows():
        student_name = _clean(student.get("StudentName"))
        father_name = _clean(student.get("FatherName"))
        teacher = _teacher_display_name(
            student.get("AssignedTeacher")
        )

        student_attendance = attendance[
            (
                attendance["StudentName"].map(_normalise)
                == _normalise(student_name)
            )
            & (
                attendance["FatherName"].map(_normalise)
                == _normalise(father_name)
            )
        ]

        student_work = work[
            (
                work["StudentName"].map(_normalise)
                == _normalise(student_name)
            )
            & (
                work["FatherName"].map(_normalise)
                == _normalise(father_name)
            )
        ]

        morning_dates = set(
            student_attendance[
                student_attendance["AttendanceSession"]
                == config.ATTENDANCE_SESSION_MORNING
            ]["Date"].tolist()
        )

        afternoon_dates = set(
            student_attendance[
                student_attendance["AttendanceSession"]
                == config.ATTENDANCE_SESSION_AFTERNOON
            ]["Date"].tolist()
        )

        sabaq_dates = set()
        sabqi_dates = set()
        manzil_dates = set()
        pao_dates = set()

        for _, work_row in student_work.iterrows():
            work_date = _clean(work_row.get("Date"))

            if _work_present(work_row, config.WORK_SABAQ):
                sabaq_dates.add(work_date)
            if _work_present(work_row, config.WORK_SABQI):
                sabqi_dates.add(work_date)
            if _work_present(work_row, config.WORK_MANZIL):
                manzil_dates.add(work_date)
            if _work_present(work_row, config.WORK_PAO):
                pao_dates.add(work_date)

        rows.append(
            {
                "طالب علم": student_name,
                "والد کا نام": father_name,
                "مقرر استاد": teacher,
                config.REPORT_EDUCATIONAL_DAYS: len(date_strings),
                config.REPORT_MORNING_UNMARKED: sum(
                    item not in morning_dates
                    for item in date_strings
                ),
                config.REPORT_AFTERNOON_UNMARKED: sum(
                    item not in afternoon_dates
                    for item in date_strings
                ),
                config.REPORT_SABAQ_UNMARKED: sum(
                    item not in sabaq_dates
                    for item in date_strings
                ),
                config.REPORT_SABQI_UNMARKED: sum(
                    item not in sabqi_dates
                    for item in date_strings
                ),
                config.REPORT_MANZIL_UNMARKED: sum(
                    item not in manzil_dates
                    for item in date_strings
                ),
                "پاؤ غیر درج شدہ": sum(
                    item not in pao_dates
                    for item in date_strings
                ),
            }
        )

    return pd.DataFrame(rows)


def render_missing_submissions_report():
    st.subheader("⚠️ ماہانہ غیر درج شدہ اندراجات")

    month = st.text_input(
        "مہینہ درج کریں (YYYY-MM)",
        value=today_str()[:7],
        key="missing_report_month",
    ).strip()

    if not _valid_month(month):
        error_message(
            "مہینہ درست فارمیٹ YYYY-MM میں درج کریں۔"
        )
        return

    students = _active_students()

    if students.empty:
        info_message("کوئی فعال طالب علم موجود نہیں۔")
        return

    attendance = _prepare_attendance_dataframe(
        sheets.get_all_attendance()
    )
    attendance = attendance[
        attendance["Date"].str.startswith(month)
    ].copy()

    work = _prepare_daily_work_dataframe(
        sheets.get_all_daily_work()
    )
    work = work[
        work["Date"].str.startswith(month)
    ].copy()

    educational_dates = _educational_dates(month)
    report = _build_missing_report(
        students,
        attendance,
        work,
        educational_dates,
    )

    teacher_options = sorted(
        value
        for value in report["مقرر استاد"].unique()
        if _clean(value)
    )

    selected_teacher = st.selectbox(
        "استاد کے مطابق فلٹر کریں",
        ["تمام"] + teacher_options,
        key="missing_teacher_filter",
    )

    if selected_teacher != "تمام":
        report = report[
            report["مقرر استاد"] == selected_teacher
        ]

    st.caption(
        f"تعلیمی ایام: {len(educational_dates)} "
        "(جمعہ خارج ہے)"
    )

    st.dataframe(report, use_container_width=True, hide_index=True)
    _render_export_buttons(
        report,
        f"missing_submissions_{month}",
        "Missing Submissions Report",
        month,
    )


def render_charts_and_statistics():
    st.subheader("📈 حاضری کے چارٹس اور شماریات")

    attendance = _prepare_attendance_dataframe(
        sheets.get_all_attendance()
    )

    if attendance.empty:
        info_message(
            "چارٹس کے لیے کوئی حاضری ریکارڈ موجود نہیں۔"
        )
        return

    render_attendance_stats(attendance)
    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### مجموعی حاضری کی تقسیم")

        status_counts = (
            attendance["Status"]
            .value_counts()
            .rename_axis("حیثیت")
            .reset_index(name="تعداد")
        )

        fig = px.pie(
            status_counts,
            names="حیثیت",
            values="تعداد",
            color="حیثیت",
            color_discrete_map=config.ATTENDANCE_COLORS,
            hole=0.45,
        )

        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("#### صبح اور دوپہر کی حاضری")

        session_counts = (
            attendance.groupby(
                ["AttendanceSession", "Status"]
            )
            .size()
            .reset_index(name="تعداد")
        )

        fig = px.bar(
            session_counts,
            x="AttendanceSession",
            y="تعداد",
            color="Status",
            barmode="group",
            labels={
                "AttendanceSession": "حاضری کا وقت",
                "Status": "حیثیت",
            },
            color_discrete_map=config.ATTENDANCE_COLORS,
        )

        st.plotly_chart(fig, use_container_width=True)

    col3, col4 = st.columns(2)

    with col3:
        st.markdown("#### تازہ ترین 30 دن کا رجحان")

        daily_counts = (
            attendance[
                attendance["Status"].isin(
                    [
                        config.STATUS_PRESENT,
                        config.STATUS_LATE,
                    ]
                )
            ]
            .groupby(["Date", "AttendanceSession"])
            .size()
            .reset_index(name="تعداد")
        )

        daily_counts["_ParsedDate"] = pd.to_datetime(
            daily_counts["Date"],
            errors="coerce",
        )
        daily_counts = (
            daily_counts
            .sort_values("_ParsedDate")
            .tail(60)
        )

        fig = px.line(
            daily_counts,
            x="Date",
            y="تعداد",
            color="AttendanceSession",
            markers=True,
            labels={
                "Date": "تاریخ",
                "AttendanceSession": "حاضری کا وقت",
            },
        )

        st.plotly_chart(fig, use_container_width=True)

    with col4:
        st.markdown("#### اساتذہ کے درج کردہ ریکارڈز")

        teacher_counts = (
            attendance[
                attendance["TeacherName"].str.strip() != ""
            ]
            .groupby("TeacherName")
            .size()
            .reset_index(name="کل ریکارڈز")
            .rename(columns={"TeacherName": "استاد"})
        )

        if teacher_counts.empty:
            info_message(
                "اساتذہ کے موازنے کے لیے کافی ڈیٹا موجود نہیں۔"
            )
        else:
            fig = px.bar(
                teacher_counts,
                x="استاد",
                y="کل ریکارڈز",
                color_discrete_sequence=[
                    config.COLOR_ACCENT
                ],
            )

            st.plotly_chart(fig, use_container_width=True)
