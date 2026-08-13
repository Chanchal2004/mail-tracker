import os
import re
import sqlite3
import secrets
import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape

from flask import (
    Flask,
    request,
    jsonify,
    render_template_string,
)

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# ============================================================
# APP CONFIG
# ============================================================

APP = Flask(__name__)

HOST = "127.0.0.1"
PORT = 5000

DB_FILE = "tracker.db"

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"

SENDER_EMAIL = "chanchalchaudhary0101@gmail.com"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send"
]


# ============================================================
# CLOUDFLARE PUBLIC URL
# ============================================================
#
# Current Quick Tunnel:
#
# https://performer-wooden-pipes-mrna.trycloudflare.com
#
# IMPORTANT:
# If cloudflared gives you a NEW URL after restart,
# change this value.
#
# You can also set:
#
# set PUBLIC_URL=https://your-url.trycloudflare.com
#
# ============================================================

PUBLIC_URL = os.environ.get(
    "PUBLIC_URL",
    "https://performer-wooden-pipes-mrna.trycloudflare.com"
).rstrip("/")


# ============================================================
# DATABASE
# ============================================================

def get_db():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA journal_mode=WAL"
    )

    conn.execute(
        "PRAGMA foreign_keys=ON"
    )

    return conn


def utc_now():

    return datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )


def init_db():

    conn = get_db()

    cur = conn.cursor()

    # --------------------------------------------------------
    # EMAILS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS emails (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tracking_id TEXT UNIQUE NOT NULL,

            recipient TEXT NOT NULL,

            subject TEXT,

            sent_at TEXT,

            gmail_message_id TEXT,

            first_opened_at TEXT,

            last_opened_at TEXT,

            open_count INTEGER NOT NULL DEFAULT 0,

            first_clicked_at TEXT,

            last_clicked_at TEXT,

            click_count INTEGER NOT NULL DEFAULT 0,

            first_page_visit_at TEXT,

            last_page_visit_at TEXT,

            page_visit_count INTEGER NOT NULL DEFAULT 0
        )
    """)

    # --------------------------------------------------------
    # ACTIVITY
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tracking_id TEXT NOT NULL,

            event TEXT NOT NULL,

            timestamp TEXT NOT NULL,

            ip TEXT,

            user_agent TEXT,

            referer TEXT,

            name TEXT,

            email TEXT,

            FOREIGN KEY (
                tracking_id
            )
            REFERENCES emails(
                tracking_id
            )
            ON DELETE CASCADE
        )
    """)

    # --------------------------------------------------------
    # INDEXES
    # --------------------------------------------------------

    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_activity_tracking_id
        ON activity(tracking_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_activity_timestamp
        ON activity(timestamp)
    """)

    conn.commit()
    conn.close()

    print(
        "Database ready:",
        DB_FILE
    )


# ============================================================
# GOOGLE GMAIL AUTH
# ============================================================

def gmail_service():

    creds = None

    # --------------------------------------------------------
    # Existing token
    # --------------------------------------------------------

    if os.path.exists(
        TOKEN_FILE
    ):

        try:

            creds = (
                Credentials
                .from_authorized_user_file(
                    TOKEN_FILE,
                    SCOPES
                )
            )

        except Exception as e:

            print(
                "Existing token could not be loaded:",
                e
            )

            creds = None

    # --------------------------------------------------------
    # Refresh token
    # --------------------------------------------------------

    if (
        creds
        and creds.expired
        and creds.refresh_token
    ):

        try:

            creds.refresh(
                Request()
            )

        except Exception as e:

            print(
                "Token refresh failed:",
                e
            )

            creds = None

    # --------------------------------------------------------
    # New OAuth login
    # --------------------------------------------------------

    if not creds or not creds.valid:

        if not os.path.exists(
            CREDENTIALS_FILE
        ):

            raise FileNotFoundError(
                "credentials.json nahi mila. "
                "Isko app.py ke same folder mein rakho."
            )

        print()
        print(
            "Opening Google OAuth..."
        )

        flow = (
            InstalledAppFlow
            .from_client_secrets_file(
                CREDENTIALS_FILE,
                SCOPES
            )
        )

        creds = flow.run_local_server(
            port=0
        )

        # ----------------------------------------------------
        # token.json AUTOMATICALLY CREATED
        # ----------------------------------------------------

        with open(
            TOKEN_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                creds.to_json()
            )

        print(
            "token.json created."
        )

    return build(
        "gmail",
        "v1",
        credentials=creds
    )


# ============================================================
# EMAIL VALIDATION
# ============================================================

EMAIL_REGEX = re.compile(
    r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
)


def valid_email(value):

    return bool(
        EMAIL_REGEX.match(
            str(value).strip()
        )
    )


# ============================================================
# REQUEST INFORMATION
# ============================================================

def request_ip():

    # Cloudflare
    cf_ip = request.headers.get(
        "CF-Connecting-IP"
    )

    if cf_ip:
        return cf_ip

    # Proxy
    forwarded = request.headers.get(
        "X-Forwarded-For"
    )

    if forwarded:

        return (
            forwarded
            .split(",")[0]
            .strip()
        )

    return (
        request.remote_addr
        or ""
    )


def request_user_agent():

    return request.headers.get(
        "User-Agent",
        ""
    )


def request_referer():

    return request.headers.get(
        "Referer",
        ""
    )


# ============================================================
# CHECK TRACKING ID
# ============================================================

def tracking_exists(
    tracking_id
):

    conn = get_db()

    row = conn.execute("""
        SELECT tracking_id
        FROM emails
        WHERE tracking_id = ?
    """, (
        tracking_id,
    )).fetchone()

    conn.close()

    return row is not None


# ============================================================
# ACTIVITY LOGGER
# ============================================================

def log_activity(
    tracking_id,
    event,
    name=None,
    email=None
):

    now = utc_now()

    conn = get_db()

    # --------------------------------------------------------
    # Verify tracking ID
    # --------------------------------------------------------

    row = conn.execute("""
        SELECT tracking_id
        FROM emails
        WHERE tracking_id = ?
    """, (
        tracking_id,
    )).fetchone()

    if not row:

        conn.close()

        return False

    # --------------------------------------------------------
    # Store event
    # --------------------------------------------------------

    conn.execute("""
        INSERT INTO activity (

            tracking_id,
            event,
            timestamp,
            ip,
            user_agent,
            referer,
            name,
            email

        )

        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?
        )
    """, (
        tracking_id,
        event,
        now,
        request_ip(),
        request_user_agent(),
        request_referer(),
        name,
        email
    ))

    # --------------------------------------------------------
    # OPEN
    # --------------------------------------------------------

    if event == "open":

        conn.execute("""
            UPDATE emails

            SET

                first_opened_at =
                    COALESCE(
                        first_opened_at,
                        ?
                    ),

                last_opened_at = ?,

                open_count =
                    COALESCE(
                        open_count,
                        0
                    ) + 1

            WHERE tracking_id = ?
        """, (
            now,
            now,
            tracking_id
        ))

    # --------------------------------------------------------
    # CLICK
    # --------------------------------------------------------

    elif event == "click":

        conn.execute("""
            UPDATE emails

            SET

                first_clicked_at =
                    COALESCE(
                        first_clicked_at,
                        ?
                    ),

                last_clicked_at = ?,

                click_count =
                    COALESCE(
                        click_count,
                        0
                    ) + 1

            WHERE tracking_id = ?
        """, (
            now,
            now,
            tracking_id
        ))

    # --------------------------------------------------------
    # PAGE VISIT
    # --------------------------------------------------------

    elif event == "page_visit":

        conn.execute("""
            UPDATE emails

            SET

                first_page_visit_at =
                    COALESCE(
                        first_page_visit_at,
                        ?
                    ),

                last_page_visit_at = ?,

                page_visit_count =
                    COALESCE(
                        page_visit_count,
                        0
                    ) + 1

            WHERE tracking_id = ?
        """, (
            now,
            now,
            tracking_id
        ))

    conn.commit()

    conn.close()

    return True


# ============================================================
# CREATE EMAIL HTML
# ============================================================

def create_email_html(
    recipient,
    subject,
    tracking_id,
    message
):

    tracking_url = (
        PUBLIC_URL
        + "/go/"
        + tracking_id
    )

    pixel_url = (
        PUBLIC_URL
        + "/track/"
        + tracking_id
        + ".gif"
    )

    safe_message = escape(
        message
    )

    safe_tracking_url = escape(
        tracking_url
    )

    safe_pixel_url = escape(
        pixel_url
    )

    html = f"""
<!doctype html>

<html>

<head>

<meta charset="utf-8">

</head>

<body>

<div>

{safe_message}

</div>

<br>

<div>

<a
    href="{safe_tracking_url}"
    target="_blank"
    rel="noopener noreferrer"
>
    Continue
</a>

</div>

<br>

<p
    style="
        font-size:12px;
        color:#777;
    "
>
    This link is provided for the recipient's
    voluntary use.
</p>


<!-- EMAIL TRACKING PIXEL -->

<img
    src="{safe_pixel_url}"
    width="1"
    height="1"
    style="display:none"
    alt=""
>

</body>

</html>
"""

    return html


# ============================================================
# SEND ONE EMAIL
# ============================================================

def send_one_email(
    service,
    recipient,
    subject,
    message
):

    # --------------------------------------------------------
    # UNIQUE TRACKING ID
    # --------------------------------------------------------

    tracking_id = secrets.token_urlsafe(
        32
    )

    sent_at = utc_now()

    html = create_email_html(
        recipient,
        subject,
        tracking_id,
        message
    )

    # --------------------------------------------------------
    # EMAIL MESSAGE
    # --------------------------------------------------------

    msg = EmailMessage()

    msg["To"] = recipient

    msg["From"] = SENDER_EMAIL

    msg["Subject"] = subject

    # Plain-text version
    msg.set_content(
        message
    )

    # HTML version
    msg.add_alternative(
        html,
        subtype="html"
    )

    # --------------------------------------------------------
    # Gmail raw message
    # --------------------------------------------------------

    raw = base64.urlsafe_b64encode(
        msg.as_bytes()
    ).decode()
    result = (
        service
        .users()
        .messages()
        .send(
            userId="me",
            body={
                "raw": raw
            }
        )
        .execute()
    )

    gmail_message_id = (
        result.get("id")
    )

    # --------------------------------------------------------
    # SAVE BEFORE RETURN
    # --------------------------------------------------------

    conn = get_db()

    conn.execute("""
        INSERT INTO emails (

            tracking_id,
            recipient,
            subject,
            sent_at,
            gmail_message_id

        )

        VALUES (
            ?, ?, ?, ?, ?
        )
    """, (
        tracking_id,
        recipient,
        subject,
        sent_at,
        gmail_message_id
    ))

    conn.commit()

    conn.close()

    return {

        "success": True,

        "tracking_id":
            tracking_id,

        "recipient":
            recipient,

        "message_id":
            gmail_message_id,

        "tracking_url":
            PUBLIC_URL
            + "/go/"
            + tracking_id
    }


# ============================================================
# DASHBOARD
# ============================================================

@APP.get("/")
def dashboard():

    conn = get_db()

    emails = conn.execute("""
        SELECT *
        FROM emails
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template_string(
        DASHBOARD_HTML,
        emails=emails,
        public_url=PUBLIC_URL,
        sender=SENDER_EMAIL
    )


# ============================================================
# SEND FORM
# ============================================================

@APP.post("/send")
def send_from_dashboard():

    recipients_text = (
        request.form.get(
            "recipients",
            ""
        )
    )

    subject = (
        request.form.get(
            "subject",
            ""
        ).strip()
    )

    message = (
        request.form.get(
            "message",
            ""
        ).strip()
    )

    # --------------------------------------------------------
    # Parse recipients
    # --------------------------------------------------------

    raw_recipients = re.split(
        r"[\n,;]+",
        recipients_text
    )

    recipients = []

    invalid = []

    for item in raw_recipients:

        email = item.strip()

        if not email:
            continue

        if valid_email(email):

            if email.lower() not in [
                x.lower()
                for x in recipients
            ]:

                recipients.append(
                    email
                )

        else:

            invalid.append(
                email
            )

    # --------------------------------------------------------
    # Validate
    # --------------------------------------------------------

    if not recipients:

        return render_template_string(
            MESSAGE_HTML,
            title="Error",
            message="At least one valid recipient email required.",
            back=True
        ), 400

    if not subject:

        return render_template_string(
            MESSAGE_HTML,
            title="Error",
            message="Subject required.",
            back=True
        ), 400

    if not message:

        return render_template_string(
            MESSAGE_HTML,
            title="Error",
            message="Message required.",
            back=True
        ), 400

    # --------------------------------------------------------
    # Gmail
    # --------------------------------------------------------

    try:

        service = gmail_service()

    except Exception as e:

        return render_template_string(
            MESSAGE_HTML,
            title="Gmail Login Error",
            message=str(e),
            back=True
        ), 500

    results = []

    # --------------------------------------------------------
    # Send each recipient separately
    # --------------------------------------------------------

    for recipient in recipients:

        try:

            result = send_one_email(
                service,
                recipient,
                subject,
                message
            )

            results.append(
                result
            )

        except Exception as e:

            results.append({

                "success":
                    False,

                "recipient":
                    recipient,

                "error":
                    str(e)
            })

    # --------------------------------------------------------
    # Result page
    # --------------------------------------------------------

    return render_template_string(
        SEND_RESULT_HTML,
        results=results,
        invalid=invalid
    )


# ============================================================
# TRACKING PIXEL
# ============================================================

GIF_1X1 = (
    b"GIF89a"
    b"\x01\x00\x01\x00"
    b"\x80\x00\x00"
    b"\x00\x00\x00"
    b"\xff\xff\xff"
    b"!\xf9\x04\x01"
    b"\x00\x00\x00\x00"
    b",\x00\x00\x00\x00"
    b"\x01\x00\x01\x00"
    b"\x00\x02\x02"
    b"D\x01\x00;"
)


@APP.get(
    "/track/<tracking_id>.gif"
)
def track_open(tracking_id):

    # --------------------------------------------------------
    # Only record valid IDs
    # --------------------------------------------------------

    if tracking_exists(
        tracking_id
    ):

        log_activity(
            tracking_id,
            "open"
        )

    response = APP.response_class(
        GIF_1X1,
        status=200,
        mimetype="image/gif"
    )

    response.headers[
        "Cache-Control"
    ] = (
        "no-store, "
        "no-cache, "
        "must-revalidate, "
        "max-age=0"
    )

    response.headers[
        "Pragma"
    ] = "no-cache"

    response.headers[
        "Expires"
    ] = "0"

    return response


# ============================================================
# TRACKED EMAIL LINK
# ============================================================

@APP.get(
    "/go/<tracking_id>"
)
def tracked_link(tracking_id):

    if not tracking_exists(
        tracking_id
    ):

        return render_template_string(
            MESSAGE_HTML,
            title="Invalid Link",
            message="This tracking link is invalid or expired.",
            back=False
        ), 404

    # --------------------------------------------------------
    # CLICK
    # --------------------------------------------------------

    log_activity(
        tracking_id,
        "click"
    )

    # --------------------------------------------------------
    # Landing page
    # --------------------------------------------------------

    return render_template_string(
        LANDING_HTML,
        tracking_id=tracking_id
    )


# ============================================================
# PAGE ACTIVITY
# ============================================================

@APP.post(
    "/api/activity/<tracking_id>"
)
def activity_api(tracking_id):

    if not tracking_exists(
        tracking_id
    ):

        return jsonify({
            "success": False,
            "error": "Invalid tracking ID"
        }), 404

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    event = data.get(
        "event"
    )

    # --------------------------------------------------------
    # PAGE VISIT
    # --------------------------------------------------------

    if event == "page_visit":

        log_activity(
            tracking_id,
            "page_visit"
        )

        return jsonify({
            "success": True
        })

    # --------------------------------------------------------
    # VOLUNTARY FORM SUBMISSION
    # --------------------------------------------------------

    if event == "form_submit":

        name = str(
            data.get(
                "name",
                ""
            )
        ).strip()

        email = str(
            data.get(
                "email",
                ""
            )
        ).strip()

        if not name:

            return jsonify({
                "success": False,
                "error": "Name required"
            }), 400

        if not valid_email(
            email
        ):

            return jsonify({
                "success": False,
                "error":
                    "Valid email required"
            }), 400

        # Reasonable storage limits
        name = name[:200]
        email = email[:320]

        log_activity(
            tracking_id,
            "form_submit",
            name=name,
            email=email
        )

        return jsonify({
            "success": True
        })

    return jsonify({
        "success": False,
        "error": "Invalid event"
    }), 400


# ============================================================
# ACTIVITY JSON
# ============================================================

@APP.get(
    "/api/activity/<tracking_id>"
)
def get_activity(tracking_id):

    if not tracking_exists(
        tracking_id
    ):

        return jsonify({
            "error": "Invalid tracking ID"
        }), 404

    conn = get_db()

    rows = conn.execute("""
        SELECT

            id,
            event,
            timestamp,
            ip,
            user_agent,
            referer,
            name,
            email

        FROM activity

        WHERE tracking_id = ?

        ORDER BY id ASC
    """, (
        tracking_id,
    )).fetchall()

    conn.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


# ============================================================
# EMAIL API
# ============================================================

@APP.get(
    "/api/emails"
)
def get_emails():

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM emails
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


# ============================================================
# HEALTH CHECK
# ============================================================

@APP.get(
    "/health"
)
def health():

    return jsonify({

        "ok":
            True,

        "application":
            "email-tracker",

        "sender":
            SENDER_EMAIL,

        "public_url":
            PUBLIC_URL,

        "time_utc":
            utc_now()
    })


# ============================================================
# DASHBOARD HTML
# ============================================================

DASHBOARD_HTML = """
<!doctype html>

<html>

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>Email Tracker</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    padding: 25px;

    font-family:
        Arial,
        sans-serif;

    background:
        #f4f6f9;

    color:
        #222;
}

.container {

    max-width:
        1400px;

    margin:
        auto;
}

.card {

    background:
        white;

    border-radius:
        14px;

    padding:
        24px;

    margin-bottom:
        20px;

    box-shadow:
        0 3px 18px
        rgba(0,0,0,.07);
}

h1 {

    margin-top: 0;
}

h2 {

    margin-top: 0;
}

label {

    display:
        block;

    font-weight:
        600;

    margin-top:
        15px;

    margin-bottom:
        6px;
}

input,
textarea {

    width:
        100%;

    padding:
        12px;

    border:
        1px solid #ccc;

    border-radius:
        8px;

    font-size:
        15px;

    font-family:
        inherit;
}

textarea {

    min-height:
        140px;

    resize:
        vertical;
}

button {

    margin-top:
        18px;

    padding:
        12px 22px;

    background:
        #222;

    color:
        white;

    border:
        0;

    border-radius:
        8px;

    cursor:
        pointer;

    font-size:
        15px;
}

.public-url {

    background:
        #f0f2f5;

    padding:
        10px;

    border-radius:
        7px;

    word-break:
        break-all;

    font-family:
        monospace;
}

.table-wrap {

    overflow-x:
        auto;
}

table {

    width:
        100%;

    border-collapse:
        collapse;

    min-width:
        1200px;
}

th,
td {

    padding:
        11px;

    border-bottom:
        1px solid #ddd;

    text-align:
        left;

    vertical-align:
        top;
}

th {

    background:
        #f0f0f0;
}

.badge {

    display:
        inline-block;

    padding:
        4px 8px;

    border-radius:
        6px;

    background:
        #eee;

    font-weight:
        600;
}

.small {

    font-size:
        12px;

    color:
        #666;

    line-height:
        1.5;
}

a {

    color:
        #1261a0;

    text-decoration:
        none;
}

a:hover {

    text-decoration:
        underline;
}

</style>

</head>

<body>

<div class="container">


<!-- ===================================================== -->
<!-- HEADER -->
<!-- ===================================================== -->

<div class="card">

<h1>
Email Tracker
</h1>

<p>
<strong>From:</strong>
{{ sender }}
</p>

<p>
<strong>Cloudflare Public URL:</strong>
</p>

<div class="public-url">
{{ public_url }}
</div>

<p class="small">
Open tracking records a request for the email's
tracking image. Mail providers may automatically
request/cache images, so an open event is not
guaranteed proof that a person viewed the email.
</p>

</div>


<!-- ===================================================== -->
<!-- SEND EMAIL -->
<!-- ===================================================== -->

<div class="card">

<h2>
Send Email
</h2>

<form
    method="POST"
    action="/send"
>

<label>
Recipients
</label>

<textarea
    name="recipients"
    placeholder="one@example.com
two@example.com
three@example.com"
    required
></textarea>

<p class="small">
You can enter one email per line, or separate
emails with commas.
</p>


<label>
Subject
</label>

<input
    type="text"
    name="subject"
    placeholder="Email subject"
    required
>


<label>
Message
</label>

<textarea
    name="message"
    placeholder="Write your email message here..."
    required
></textarea>


<button
    type="submit"
>
Send Email
</button>

</form>

</div>


<!-- ===================================================== -->
<!-- TRACKING TABLE -->
<!-- ===================================================== -->

<div class="card">

<h2>
Tracking
</h2>

<div class="table-wrap">

<table>

<thead>

<tr>

<th>
Recipient
</th>

<th>
Subject
</th>

<th>
Sent
</th>

<th>
Opened
</th>

<th>
First Open
</th>

<th>
Last Open
</th>

<th>
Clicks
</th>

<th>
First Click
</th>

<th>
Last Click
</th>

<th>
Page Visits
</th>

<th>
Activity
</th>

</tr>

</thead>

<tbody>

{% for e in emails %}

<tr>

<td>
{{ e["recipient"] }}
</td>

<td>
{{ e["subject"] or "-" }}
</td>

<td>
{{ e["sent_at"] or "-" }}
</td>

<td>

<span class="badge">
{{ e["open_count"] or 0 }}
</span>

</td>

<td>
{{ e["first_opened_at"] or "-" }}
</td>

<td>
{{ e["last_opened_at"] or "-" }}
</td>

<td>

<span class="badge">
{{ e["click_count"] or 0 }}
</span>

</td>

<td>
{{ e["first_clicked_at"] or "-" }}
</td>

<td>
{{ e["last_clicked_at"] or "-" }}
</td>

<td>

<span class="badge">
{{ e["page_visit_count"] or 0 }}
</span>

</td>

<td>

<a
    href="/api/activity/{{ e["tracking_id"] }}"
    target="_blank"
>
Activity
</a>

<br>

<a
    href="/go/{{ e["tracking_id"] }}"
    target="_blank"
>
Test link
</a>

</td>

</tr>

{% else %}

<tr>

<td colspan="11">
No emails sent yet.
</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

</div>

</div>

</body>

</html>
"""


# ============================================================
# SEND RESULT HTML
# ============================================================

SEND_RESULT_HTML = """
<!doctype html>

<html>

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>Send Result</title>

<style>

body {

    font-family:
        Arial,
        sans-serif;

    background:
        #f4f6f9;

    padding:
        30px;
}

.card {

    max-width:
        900px;

    margin:
        auto;

    background:
        white;

    padding:
        25px;

    border-radius:
        12px;

    box-shadow:
        0 4px 20px
        rgba(0,0,0,.08);
}

.result {

    padding:
        15px;

    margin:
        10px 0;

    border-radius:
        8px;

    background:
        #f3f3f3;
}

.success {

    border-left:
        5px solid #22a06b;
}

.error {

    border-left:
        5px solid #d64545;
}

a {

    color:
        #1261a0;
}

</style>

</head>

<body>

<div class="card">

<h2>
Send Result
</h2>


{% for r in results %}

{% if r.get("success") %}

<div class="result success">

<strong>
Sent:
</strong>

{{ r["recipient"] }}

<br><br>

<strong>
Tracking URL:
</strong>

<br>

<a
    href="{{ r["tracking_url"] }}"
    target="_blank"
>
{{ r["tracking_url"] }}
</a>

<br><br>

<strong>
Tracking ID:
</strong>

{{ r["tracking_id"] }}

</div>

{% else %}

<div class="result error">

<strong>
Failed:
</strong>

{{ r.get("recipient", "-") }}

<br>

{{ r.get("error", "Unknown error") }}

</div>

{% endif %}

{% endfor %}


{% if invalid %}

<h3>
Invalid addresses
</h3>

<ul>

{% for x in invalid %}

<li>
{{ x }}
</li>

{% endfor %}

</ul>

{% endif %}


<p>

<a href="/">
← Back to Dashboard
</a>

</p>

</div>

</body>

</html>
"""


# ============================================================
# GENERIC MESSAGE PAGE
# ============================================================

MESSAGE_HTML = """
<!doctype html>

<html>

<head>

<meta charset="utf-8">

<title>{{ title }}</title>

<style>

body {

    font-family:
        Arial,
        sans-serif;

    background:
        #f4f6f9;

    padding:
        40px;
}

.card {

    max-width:
        600px;

    margin:
        auto;

    background:
        white;

    padding:
        30px;

    border-radius:
        12px;
}

a {

    color:
        #1261a0;
}

</style>

</head>

<body>

<div class="card">

<h2>
{{ title }}
</h2>

<p>
{{ message }}
</p>

{% if back %}

<p>
<a href="/">
← Back
</a>
</p>

{% endif %}

</div>

</body>

</html>
"""


# ============================================================
# LANDING PAGE
# ============================================================

LANDING_HTML = """
<!doctype html>

<html>

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>Continue</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin:
        0;

    padding:
        30px;

    background:
        #f5f7fb;

    font-family:
        Arial,
        sans-serif;
}

.card {

    max-width:
        460px;

    margin:
        60px auto;

    padding:
        30px;

    background:
        white;

    border-radius:
        14px;

    box-shadow:
        0 5px 25px
        rgba(0,0,0,.08);
}

input {

    width:
        100%;

    padding:
        12px;

    margin:
        7px 0 15px;

    border:
        1px solid #ccc;

    border-radius:
        7px;
}

label {

    display:
        block;

    font-weight:
        600;
}

button {

    width:
        100%;

    padding:
        12px;

    background:
        #222;

    color:
        white;

    border:
        0;

    border-radius:
        7px;

    cursor:
        pointer;
}

.small {

    font-size:
        13px;

    color:
        #666;

    line-height:
        1.5;
}

#status {

    margin-top:
        15px;
}

</style>

</head>

<body>

<div class="card">

<h2>
Continue
</h2>

<p>
You can voluntarily submit your name and email
for this page.
</p>

<form id="form">

<label>
Name
</label>

<input
    id="name"
    autocomplete="name"
    required
>


<label>
Email
</label>

<input
    id="email"
    type="email"
    autocomplete="email"
    required
>


<p class="small">
Only information that you voluntarily enter
in this form is submitted.
</p>


<button
    id="submitButton"
    type="submit"
>
Continue
</button>

</form>


<div id="status">
</div>

</div>


<script>

const trackingId =
    "{{ tracking_id }}";

const form =
    document.getElementById(
        "form"
    );

const button =
    document.getElementById(
        "submitButton"
    );

const status =
    document.getElementById(
        "status"
    );


// ==========================================================
// PAGE VISIT
// ==========================================================

fetch(
    "/api/activity/" + trackingId,
    {

        method:
            "POST",

        headers: {
            "Content-Type":
                "application/json"
        },

        body: JSON.stringify({
            event:
                "page_visit"
        })
    }
).catch(
    () => {}
);


// ==========================================================
// FORM SUBMIT
// ==========================================================

form.addEventListener(
    "submit",
    async function(event) {

        event.preventDefault();

        button.disabled = true;

        status.textContent =
            "Submitting...";

        const name =
            document
            .getElementById(
                "name"
            )
            .value
            .trim();

        const email =
            document
            .getElementById(
                "email"
            )
            .value
            .trim();

        try {

            const response =
                await fetch(
                    "/api/activity/" +
                    trackingId,
                    {

                        method:
                            "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify({

                                event:
                                    "form_submit",

                                name:
                                    name,

                                email:
                                    email
                            })
                    }
                );

            const data =
                await response.json();

            if (response.ok) {

                status.textContent =
                    "Submitted successfully.";

                form.reset();

            } else {

                status.textContent =
                    data.error ||
                    "Submission failed.";

            }

        } catch (error) {

            status.textContent =
                "Network error.";

        } finally {

            button.disabled = false;
        }

    }
);

</script>

</body>

</html>
"""


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 70)
    print("EMAIL TRACKER")
    print("=" * 70)

    print()
    print("Sender:")
    print(SENDER_EMAIL)

    print()
    print("Public URL:")
    print(PUBLIC_URL)

    print()
    print("Dashboard:")
    print(
        f"http://127.0.0.1:{PORT}/"
    )

    print()
    print("Health:")
    print(
        f"http://127.0.0.1:{PORT}/health"
    )

    print()
    print("Database:")
    print(DB_FILE)

    print()
    print("Gmail token:")
    print(TOKEN_FILE)

    print()
    print("=" * 70)

    # Create fresh DB if it doesn't exist
    init_db()

    APP.run(
        host=HOST,
        port=PORT,
        debug=False,
        threaded=True
    )