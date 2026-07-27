# Madarsa Attendance Portal

Madarsa Attendance Portal is a professional, web-based attendance management system designed for Hifz departments in a madarsa. It is built with Python and Streamlit, uses Google Sheets as its database through a Google Service Account, and provides a complete Urdu, right-to-left interface for both administrators and teachers. The system covers student management, daily attendance tracking, reporting, activity logging, and configurable settings, all backed by a lightweight, spreadsheet-based data store that requires no separate database server.

## Features

- Secure Login System: Username and password authentication with hashed passwords and session-based access control.
- Admin & Teacher Roles: Two distinct roles with separate permissions and separate navigation menus.
- Student Management: Add, edit, deactivate, and delete students, with search and filtering by roll number, name, father name, and status.
- Attendance Management: Teachers mark daily attendance for active students; administrators can mark attendance on behalf of any teacher.
- Attendance History: Full historical attendance records with filtering by date, teacher, student, and status.
- Reports & Analytics: Daily, weekly, monthly, and custom date range reports, including attendance percentage calculations and Plotly charts.
- Excel Export: Any report, student list, or log view can be exported to a downloadable Excel file.
- PDF Export: Any report, student list, or log view can be exported to a downloadable PDF file.
- Activity Logs: Every significant action in the system is recorded with the date, time, username, and description, and can be searched, filtered, and exported.
- Settings Management: Administrators can update madarsa information, change their password, manage teacher accounts, adjust theme colors, and review system and backup information.
- Google Sheets Database: All data is stored in a Google Sheets spreadsheet, with worksheets created automatically on first run.
- Password Hashing: Passwords are never stored or compared in plain text; they are hashed using a salted PBKDF2 algorithm.
- Responsive Streamlit Interface: A right-to-left, Urdu-first interface styled with an Islamic green and white theme that adapts to different screen sizes.

## Project Structure

\`\`\`
attendance_portal/
├── app.py
├── config.py
├── sheets.py
├── auth.py
├── login.py
├── dashboard.py
├── students.py
├── attendance.py
├── reports.py
├── settings.py
├── logs.py
├── utils.py
├── credentials.json
├── requirements.txt
└── README.md
\`\`\`

- **app.py**: The main entry point of the application. Configures the Streamlit page, initializes the database, checks the login state, renders the sidebar navigation, and routes to the correct page based on the logged-in user's role.
- **config.py**: Central configuration file containing the application title, Google Sheets settings, worksheet names and headers, user roles, attendance statuses, student statuses, default users, theme colors, and session state keys.
- **sheets.py**: The only file that communicates directly with Google Sheets. Provides connection handling, automatic worksheet creation, and reusable CRUD functions for users, students, attendance, logs, and settings. All other files access data exclusively through this module.
- **auth.py**: Implements the authentication system, including login, logout, password hashing and verification, session state management, and role-based access control functions such as `require_admin()` and `require_teacher()`.
- **login.py**: Renders the login page, including form validation and success or error messaging in Urdu.
- **dashboard.py**: The administrator dashboard, showing summary statistics, Plotly charts, recent attendance, and recent activity logs.
- **students.py**: The student management module, covering adding, editing, deleting, activating and deactivating students, searching, statistics, and Excel and PDF export of student lists.
- **attendance.py**: The attendance management module for both teachers (marking and same-day editing) and administrators (viewing, filtering, searching, editing, and deleting any record).
- **reports.py**: The reporting module, providing daily, weekly, monthly, and custom range reports, filters, statistics, Plotly charts, and the shared `to_excel_bytes()` and `dataframe_to_pdf_bytes()` export functions used across the project.
- **settings.py**: The settings module for madarsa information, the administrator's own password, teacher account management, theme color preferences, system information, and backup information.
- **logs.py**: The activity log module, showing every recorded action with search, filtering, statistics, export, and the ability to delete individual, selected, or all log entries.
- **utils.py**: Shared utility functions used throughout the project, including the global RTL and theme styling, password hashing helpers, date and time formatting, message helpers, and input validation helpers.
- **credentials.json**: The Google Service Account key file used to authenticate with the Google Sheets and Google Drive APIs. This file is used only for local development and must never be committed to version control.
- **requirements.txt**: The list of Python packages required to run the application.
- **README.md**: This documentation file.

## Installation

1. Clone the project to your local machine.

   \`\`\`
   git clone <repository-url>
   cd attendance_portal
   \`\`\`

2. (Optional) Create and activate a virtual environment.

   \`\`\`
   python -m venv venv
   venv\Scripts\activate
   \`\`\`

3. Install the required packages.

   \`\`\`
   pip install -r requirements.txt
   \`\`\`

4. Download your Google Service Account credentials from the Google Cloud Console, as described in the Google Sheets Setup section below.

5. Rename the downloaded key file to `credentials.json` and place it in the root of the project folder.

6. Share your Google Sheet with the Service Account's email address, granting it Editor access. If the spreadsheet does not exist yet, the application will create it automatically on first run, in which case this step can be completed after the first run.

7. Open `config.py` and review the settings, in particular `GOOGLE_SHEET_NAME` and `DEFAULT_USERS`, and adjust them before the first run if needed.

8. Run the application.

   \`\`\`
   py -m streamlit run app.py
   \`\`\`

   or, depending on your environment:

   \`\`\`
   streamlit run app.py
   \`\`\`

## Google Sheets Setup

1. Create a new project in the Google Cloud Console.
2. Enable the Google Sheets API for the project.
3. Enable the Google Drive API for the project, as it is required to allow the Service Account to create and locate the spreadsheet.
4. Create a Service Account within the project and generate a JSON key for it.
5. Download the JSON key file and rename it to `credentials.json`.
6. Open Google Sheets, create or locate the spreadsheet that matches `GOOGLE_SHEET_NAME` in `config.py`, and share it with the Service Account's email address, which can be found inside `credentials.json` under the `client_email` field. Grant this email Editor access.
7. On first run, the application will automatically create the required worksheets (Users, Students, Attendance, Logs, and Settings) inside this spreadsheet if they do not already exist.

## Default Users

The initial administrator and teacher accounts are defined in `config.py` under the `DEFAULT_USERS` list. These accounts are created automatically, with securely hashed passwords, the first time the application runs and finds the Users worksheet empty. Before running the application for the first time, review and update the usernames, full names, and passwords in `DEFAULT_USERS` to values appropriate for your madarsa. Usernames and passwords are intentionally not documented here; they should be managed only through `config.py` and, after the first run, through the password and teacher management sections of the Settings page.

## Technologies Used

- Python
- Streamlit
- Google Sheets
- gspread
- Pandas
- Plotly
- ReportLab
- OpenPyXL
- Google OAuth2 (google-auth)
- Werkzeug (password hashing)

## Security

- **Password Hashing**: All passwords are hashed using Werkzeug's salted PBKDF2 implementation before being stored. Plain-text passwords are never written to or compared against the Google Sheets database.
- **Role-Based Authorization**: Every page checks the logged-in user's role before rendering any content, ensuring that administrators and teachers only see the functionality assigned to their role.
- **Admin-Only Pages**: The dashboard, student management, full attendance records, reports, settings, and activity logs are protected by `require_admin()` and are completely inaccessible to teacher accounts.
- **Teacher Permissions**: Teachers can only mark attendance and edit the attendance they personally submitted on the current day; they cannot view administrative reports, manage students, manage other teachers, or delete attendance records.
- **Activity Logging**: Significant actions, including student changes, attendance changes, teacher account changes, password changes, and log deletions, are recorded with the date, time, username, and a description of the action for accountability and auditing.

## Future Improvements

- Email Notifications
- SMS Notifications
- Student Photos
- QR Code Attendance
- Face Recognition Attendance
- Mobile Application
- Automated Backup Scheduler
- Multi-language Support

## License

This project is licensed under the MIT License.