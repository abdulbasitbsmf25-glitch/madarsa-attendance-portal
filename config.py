# config.py
"""
مرکزی ترتیبات کی فائل

اس فائل میں پورے منصوبے کی بنیادی ترتیبات، گوگل شیٹس کے نام،
کالموں کے نام، حاضری کے اوقات، روزانہ تعلیمی کام، صارفین،
رنگ اور سیشن کیز محفوظ ہیں۔
"""

from pathlib import Path


# ==================================================
# ایپلیکیشن کی بنیادی معلومات
# ==================================================
APP_TITLE = "🕌 مدرسہ سیدنا عثمان بن عفانؓ پورٹل"
DEFAULT_SCHOOL_NAME = "مدرسہ سیدنا عثمان بن عفانؓ"
DEFAULT_LOGO_PATH = "assets/logo.png"

PAGE_ICON = "📖"
LAYOUT = "wide"
SIDEBAR_STATE = "expanded"


# ==================================================
# بنیادی راستے
# ==================================================
BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = str(BASE_DIR / "credentials.json")


# ==================================================
# گوگل شیٹ کی ترتیبات
# ==================================================
GOOGLE_SHEET_NAME = "Madarsa_Attendance_Database"

SHEET_USERS = "Users"
SHEET_STUDENTS = "Students"
SHEET_ATTENDANCE = "Attendance"
SHEET_DAILY_WORK = "DailyWork"
SHEET_LOGS = "Logs"
SHEET_SETTINGS = "Settings"


# ==================================================
# گوگل شیٹس کے کالم
# ==================================================
USERS_HEADERS = [
    "Username",
    "PasswordHash",
    "FullName",
    "Role",
    "Active",
]

STUDENTS_HEADERS = [
    "StudentName",
    "FatherName",
    "AssignedTeacher",
    "Age",
    "PhoneNumber",
    "Address",
    "AdmissionDate",
    "Status",
]

ATTENDANCE_HEADERS = [
    "Date",
    "AttendanceSession",
    "StudentName",
    "FatherName",
    "TeacherUsername",
    "TeacherName",
    "Status",
    "TimeSubmitted",
]

DAILY_WORK_HEADERS = [
    "Date",
    "StudentName",
    "FatherName",
    "TeacherUsername",
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

LOGS_HEADERS = [
    "Date",
    "Time",
    "Username",
    "Action",
]

SETTINGS_HEADERS = [
    "Key",
    "Value",
]


# ==================================================
# تاریخ اور وقت
# ==================================================
DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M:%S"
FRIDAY_WEEKDAY = 4


# ==================================================
# صارف کے کردار
# ==================================================
ROLE_ADMIN = "منتظم"
ROLE_TEACHER = "استاد"


# ==================================================
# حاضری کے اوقات
# ==================================================
ATTENDANCE_SESSION_MORNING = "صبح کی حاضری"
ATTENDANCE_SESSION_AFTERNOON = "دوپہر کی حاضری"

ATTENDANCE_SESSIONS = [
    ATTENDANCE_SESSION_MORNING,
    ATTENDANCE_SESSION_AFTERNOON,
]


# ==================================================
# حاضری کی حالتیں
# ==================================================
STATUS_PRESENT = "حاضر"
STATUS_ABSENT = "غیر حاضر"
STATUS_LATE = "تاخیر سے حاضر"
STATUS_LEAVE = "رخصت"

ATTENDANCE_STATUSES = [
    STATUS_PRESENT,
    STATUS_ABSENT,
    STATUS_LATE,
    STATUS_LEAVE,
]

ATTENDANCE_COLORS = {
    STATUS_PRESENT: "#2e7d32",
    STATUS_ABSENT: "#c62828",
    STATUS_LATE: "#f9a825",
    STATUS_LEAVE: "#1565c0",
}


# ==================================================
# روزانہ تعلیمی کام
# ==================================================
WORK_SABAQ = "سبق"
WORK_SABQI = "سبقی"
WORK_MANZIL = "منزل"
WORK_PAO = "پاؤ"

DAILY_WORK_TYPES = [
    WORK_SABAQ,
    WORK_SABQI,
    WORK_MANZIL,
    WORK_PAO,
]

JUZ_NUMBERS = list(range(1, 31))

MANZIL_AMOUNT_FULL = "مکمل"
MANZIL_AMOUNT_HALF = "نصف"
MANZIL_AMOUNT_QUARTER = "پاؤ"

MANZIL_AMOUNTS = [
    MANZIL_AMOUNT_FULL,
    MANZIL_AMOUNT_HALF,
    MANZIL_AMOUNT_QUARTER,
]

MANZIL_HALF_FIRST = "نصف اول"
MANZIL_HALF_SECOND = "نصف دوم"

MANZIL_HALVES = [
    MANZIL_HALF_FIRST,
    MANZIL_HALF_SECOND,
]

MANZIL_QUARTERS = [
    "پاؤ 1",
    "پاؤ 2",
    "پاؤ 3",
    "پاؤ 4",
]

PAO_QUARTERS = [1, 2, 3, 4]
# ==================================================
# ماہانہ رپورٹ کے عنوانات
# ==================================================
REPORT_EDUCATIONAL_DAYS = "تعلیمی ایام"
REPORT_MORNING_UNMARKED = "صبح کی غیر درج شدہ حاضری"
REPORT_AFTERNOON_UNMARKED = "دوپہر کی غیر درج شدہ حاضری"
REPORT_SABAQ_UNMARKED = "سبق غیر درج شدہ"
REPORT_SABQI_UNMARKED = "سبقی غیر درج شدہ"
REPORT_MANZIL_UNMARKED = "منزل غیر درج شدہ"
REPORT_STARTING_SABAQ = "مہینے کے آغاز کا سبق"
REPORT_ENDING_SABAQ = "مہینے کے اختتام کا سبق"
REPORT_MONTHLY_SABAQ_PROGRESS = "پورے مہینے میں پڑھا گیا سبق"


# ==================================================
# طالب علم کی حالت
# ==================================================
STUDENT_STATUS_ACTIVE = "فعال"
STUDENT_STATUS_INACTIVE = "غیر فعال"

STUDENT_STATUSES = [
    STUDENT_STATUS_ACTIVE,
    STUDENT_STATUS_INACTIVE,
]


# ==================================================
# منتظم کی ابتدائی معلومات
# ==================================================
ADMIN_INFO = {
    "Username": "admin",
    "Password": "admin123",
    "FullName": "قاری محمد اسماعیل",
    "Role": ROLE_ADMIN,
}


# ==================================================
# ابتدائی اساتذہ کے صارف نام
# ==================================================
TEACHER_USERNAMES = [
    "ifrahim",
    "amir",
    "anas",
    "khuzaima",
]


# ==================================================
# ابتدائی صارفین
# ==================================================
DEFAULT_USERS = [
    {
        "Username": "admin",
        "Password": "admin123",
        "FullName": "قاری اسماعیل",
        "Role": ROLE_ADMIN,
    },
    {
        "Username": "ifrahim",
        "Password": "ifrahim123",
        "FullName": "قاری افراہیم",
        "Role": ROLE_TEACHER,
    },
    {
        "Username": "amir",
        "Password": "amir123",
        "FullName": "قاری عامر",
        "Role": ROLE_TEACHER,
    },
    {
        "Username": "anas",
        "Password": "anas123",
        "FullName": "قاری انس",
        "Role": ROLE_TEACHER,
    },
    {
        "Username": "khuzaima",
        "Password": "khuzaima123",
        "FullName": "قاری خزیمہ",
        "Role": ROLE_TEACHER,
    },
]


# ==================================================
# تھیم کے رنگ
# ==================================================
COLOR_PRIMARY = "#0f6b3c"
COLOR_PRIMARY_LIGHT = "#e6f4ec"
COLOR_ACCENT = "#d4af37"
COLOR_WHITE = "#ffffff"
COLOR_TEXT = "#1a1a1a"
COLOR_DANGER = "#c62828"
COLOR_SUCCESS = "#2e7d32"
COLOR_WARNING = "#f9a825"


# ==================================================
# سیشن اسٹیٹ کیز
# ==================================================
SESSION_LOGGED_IN = "logged_in"
SESSION_USERNAME = "username"
SESSION_FULLNAME = "fullname"
SESSION_ROLE = "role"