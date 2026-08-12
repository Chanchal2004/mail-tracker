from flask import Flask, request, jsonify, render_template_string, Response
import sqlite3
import smtplib
import ssl
import uuid
import re
import html
import os
from datetime import datetime
from email.message import EmailMessage

app = Flask(__name__)
DB = "mail_tracker.db"

# ============================================================
# >>>>>> YAHAN APNI MAIL ID AUR APP PASSWORD DAALO <<<<<<
# ============================================================

SENDER_EMAIL = "chanchal053btcse22@igdtuw.ac.in"
APP_PASSWORD = "dcompgffjspiflkv"
# Gmail:
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465





# IMPORTANT:
# Normal Gmail password mat daalna.
# Google ka 16-character APP PASSWORD daalna.

# ============================================================
# OPEN TRACKING
# ============================================================
# Local testing:

BASE_URL = "https://maill-trackkk.onrender.com/"

# Real mail open tracking ke liye BASE_URL ko public HTTPS URL
# banana padega (for example your ngrok/cloudflare tunnel URL).

# ============================================================
# DATABASE
# ============================================================
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()
    c.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_id TEXT UNIQUE,
            sender TEXT,
            recipient TEXT,
            subject TEXT,
            status TEXT,
            sent_at TEXT,
            first_opened_at TEXT,
            last_opened_at TEXT,
            open_count INTEGER DEFAULT 0,
            error TEXT
        )
    """)
    c.commit()
    c.close()


def now():
    return datetime.now().astimezone().strftime(
        "%d %b %Y, %I:%M:%S %p"
    )


def split_emails(value):
    if isinstance(value, str):
        value = re.split(r"[\n,;]+", value)

    return list(dict.fromkeys(
        str(x).strip()
        for x in (value or [])
        if str(x).strip()
    ))


def valid_email(email):
    return bool(
        re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email)
    )


# ============================================================
# HOME
# ============================================================
@app.route("/")
def home():
    return render_template_string(HTML)


# ============================================================
# SEND MAIL
# ============================================================
@app.route("/send", methods=["POST"])
def send():
    data = request.get_json(silent=True) or {}

    # Sender/password are intentionally taken from the constants
    # at the top of this file.
    sender = SENDER_EMAIL.strip()
    password = APP_PASSWORD.strip()

    recipients = split_emails(
        data.get("recipients", [])
    )

    subject = str(
        data.get("subject", "")
    ).strip()

    message = str(
        data.get("message", "")
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------
    if not sender or sender == "YOUR_EMAIL@gmail.com":
        return jsonify({
            "success": False,
            "error": "app.py ke top par SENDER_EMAIL set karo."
        }), 400

    if not valid_email(sender):
        return jsonify({
            "success": False,
            "error": "SENDER_EMAIL valid email nahi hai."
        }), 400

    if not password or password == "xxxx xxxx xxxx xxxx":
        return jsonify({
            "success": False,
            "error": "app.py ke top par APP_PASSWORD set karo."
        }), 400

    if not recipients:
        return jsonify({
            "success": False,
            "error": "At least one recipient add karo."
        }), 400

    bad = [x for x in recipients if not valid_email(x)]

    if bad:
        return jsonify({
            "success": False,
            "error": "Invalid recipient: " + ", ".join(bad)
        }), 400

    if not subject:
        return jsonify({
            "success": False,
            "error": "Subject daalo."
        }), 400

    if not message.strip():
        return jsonify({
            "success": False,
            "error": "Message daalo."
        }), 400

    results = []

    # ========================================================
    # SMTP CONNECTION
    # ========================================================
    try:
        server = smtplib.SMTP_SSL(
            SMTP_HOST,
            SMTP_PORT,
            context=ssl.create_default_context(),
            timeout=30
        )

        server.login(sender, password)

    except Exception as e:
        return jsonify({
            "success": False,
            "sent": 0,
            "failed": len(recipients),
            "error": (
                "SMTP login failed: " + str(e)
            )
        }), 400

    # ========================================================
    # SEND TO EACH USER
    # ========================================================
    for recipient in recipients:

        tracking_id = uuid.uuid4().hex
        sent_at = now()

        # Tracking image
        tracking_url = (
            f"{BASE_URL.rstrip('/')}/track/{tracking_id}"
        )

        safe_message = (
            html.escape(message)
            .replace("\n", "<br>")
        )

        email_html = f"""
        <!doctype html>
        <html>
        <body style="
            font-family:Arial,sans-serif;
            color:#222;
            line-height:1.6;
        ">
            {safe_message}

            <img
                src="{html.escape(tracking_url,quote=True)}"
                width="1"
                height="1"
                alt=""
            >
        </body>
        </html>
        """

        msg = EmailMessage()

        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject

        msg.set_content(message)
        msg.add_alternative(
            email_html,
            subtype="html"
        )

        try:
            server.send_message(msg)

            c = db()

            c.execute("""
                INSERT INTO emails
                (
                    tracking_id,
                    sender,
                    recipient,
                    subject,
                    status,
                    sent_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                tracking_id,
                sender,
                recipient,
                subject,
                "SENT",
                sent_at
            ))

            c.commit()
            c.close()

            results.append({
                "recipient": recipient,
                "success": True
            })

        except Exception as e:

            c = db()

            c.execute("""
                INSERT INTO emails
                (
                    tracking_id,
                    sender,
                    recipient,
                    subject,
                    status,
                    sent_at,
                    error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                tracking_id,
                sender,
                recipient,
                subject,
                "FAILED",
                sent_at,
                str(e)
            ))

            c.commit()
            c.close()

            results.append({
                "recipient": recipient,
                "success": False,
                "error": str(e)
            })

    try:
        server.quit()
    except Exception:
        pass

    sent = sum(
        1 for x in results
        if x["success"]
    )

    failed = len(results) - sent

    return jsonify({
        "success": sent > 0,
        "sent": sent,
        "failed": failed,
        "results": results
    })


# ============================================================
# OPEN TRACKING
# ============================================================
@app.route("/track/<tracking_id>")
def track(tracking_id):

    opened = now()

    c = db()

    c.execute("""
        UPDATE emails
        SET
            status = 'OPENED',
            first_opened_at =
                COALESCE(first_opened_at, ?),
            last_opened_at = ?,
            open_count =
                COALESCE(open_count, 0) + 1
        WHERE tracking_id = ?
    """, (
        opened,
        opened,
        tracking_id
    ))

    c.commit()
    c.close()

    # 1x1 transparent GIF
    pixel = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
        b"\x00\x00\x00\xff\xff\xff!\xf9\x04\x01"
        b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01"
        b"\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )

    return Response(
        pixel,
        mimetype="image/gif",
        headers={
            "Cache-Control":
                "no-store, no-cache, must-revalidate, max-age=0"
        }
    )


# ============================================================
# API: EMAIL DATA
# ============================================================
@app.route("/api/emails")
def emails():

    c = db()

    rows = c.execute("""
        SELECT *
        FROM emails
        ORDER BY id DESC
    """).fetchall()

    c.close()

    return jsonify([
        dict(x)
        for x in rows
    ])


@app.route("/api/clear", methods=["POST"])
def clear():

    c = db()

    c.execute("DELETE FROM emails")

    c.commit()
    c.close()

    return jsonify({
        "success": True
    })


# ============================================================
# UI
# ============================================================
HTML = r"""
<!doctype html>
<html>

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>Mail Sender & Tracker</title>

<style>

*{
    box-sizing:border-box;
}

body{
    margin:0;
    background:
        radial-gradient(
            circle at top left,
            #263763,
            #080b12 48%,
            #030508
        );
    color:#fff;
    font-family:Arial,sans-serif;
}

.wrap{
    width:min(1500px,95%);
    margin:auto;
    padding:28px 0 60px;
}

.header{
    display:flex;
    justify-content:space-between;
    align-items:center;
    margin-bottom:20px;
}

.brand{
    display:flex;
    gap:14px;
    align-items:center;
}

.logo{
    width:50px;
    height:50px;
    border-radius:15px;
    display:grid;
    place-items:center;
    background:
        linear-gradient(135deg,#725cff,#3b82f6);
    font-size:23px;
}

.title{
    font-size:27px;
    font-weight:800;
}

.sub{
    font-size:12px;
    color:#8d99ad;
    margin-top:3px;
}

.online{
    padding:9px 14px;
    border:1px solid #28344a;
    border-radius:30px;
    background:#0d1421;
    color:#aeb9ca;
    font-size:12px;
}

.dot{
    display:inline-block;
    width:8px;
    height:8px;
    border-radius:50%;
    background:#22c55e;
    margin-right:7px;
}

.stats{
    display:grid;
    grid-template-columns:
        repeat(4,1fr);
    gap:15px;
    margin-bottom:20px;
}

.stat,
.card{
    background:rgba(9,14,24,.94);
    border:1px solid #1d283b;
    border-radius:20px;
}

.stat{
    padding:19px;
}

.sl{
    font-size:11px;
    color:#8190a6;
}

.sn{
    font-size:28px;
    font-weight:800;
    margin-top:7px;
}

.grid{
    display:grid;
    grid-template-columns:390px 1fr;
    gap:20px;
    align-items:start;
}

.card{
    padding:22px;
}

.ct{
    font-size:18px;
    font-weight:750;
}

.cs{
    font-size:12px;
    color:#718096;
    margin:4px 0 18px;
}

label{
    display:block;
    color:#aeb9ca;
    font-size:12px;
    margin-bottom:7px;
}

input,
textarea{
    width:100%;
    padding:12px;
    margin-bottom:12px;
    border:1px solid #2a374c;
    border-radius:10px;
    outline:none;
    background:#070c14;
    color:#fff;
    font-size:13px;
}

textarea{
    min-height:140px;
    resize:vertical;
}

.row{
    display:flex;
    gap:7px;
}

.row input{
    margin:0;
}

.remove{
    width:42px;
    border-radius:9px;
    border:1px solid #4b2931;
    background:#1b1014;
    color:#fca5a5;
    cursor:pointer;
}

.add{
    width:100%;
    margin:10px 0 18px;
    padding:10px;
    border-radius:9px;
    border:1px dashed #35435a;
    background:#0b111d;
    color:#aab5c6;
    cursor:pointer;
}

.send{
    width:100%;
    padding:14px;
    border:0;
    border-radius:10px;
    background:
        linear-gradient(135deg,#725cff,#3d7cff);
    color:#fff;
    font-weight:750;
    cursor:pointer;
}

.send:disabled{
    opacity:.5;
}

.result{
    margin-top:12px;
    font-size:12px;
    line-height:1.5;
    white-space:pre-wrap;
}

.note{
    padding:11px;
    margin:5px 0 18px;
    border:1px solid #27344a;
    border-radius:10px;
    background:#0b111d;
    color:#8290a5;
    font-size:10px;
    line-height:1.5;
}

.tablehead{
    display:flex;
    justify-content:space-between;
    align-items:center;
    margin-bottom:15px;
}

.clear{
    padding:8px 12px;
    border-radius:8px;
    border:1px solid #4a2a31;
    background:#1b1015;
    color:#fca5a5;
    cursor:pointer;
}

.tw{
    overflow:auto;
}

table{
    width:100%;
    min-width:1250px;
    border-collapse:collapse;
}

th{
    padding:12px 8px;
    text-align:left;
    color:#718096;
    font-size:9px;
    text-transform:uppercase;
    border-bottom:1px solid #202b3d;
}

td{
    padding:13px 8px;
    color:#d7dee9;
    font-size:11px;
    border-bottom:1px solid #172132;
    vertical-align:top;
}

.badge{
    display:inline-block;
    padding:5px 8px;
    border-radius:20px;
    font-size:9px;
    font-weight:750;
}

.sent{
    color:#93c5fd;
    background:#10203b;
}

.opened{
    color:#4ade80;
    background:#0d281a;
}

.failed{
    color:#f87171;
    background:#301217;
}

.empty{
    text-align:center;
    padding:50px;
    color:#64748b;
}

.err{
    color:#f87171;
    max-width:300px;
}

@media(max-width:1000px){

    .grid{
        grid-template-columns:1fr;
    }

    .stats{
        grid-template-columns:
            repeat(2,1fr);
    }

}

@media(max-width:600px){

    .online{
        display:none;
    }

}

</style>

</head>

<body>

<div class="wrap">

<div class="header">

<div class="brand">

<div class="logo">✉</div>

<div>

<div class="title">
Mail Sender & Open Tracker
</div>

<div class="sub">
Send • Multiple users • Open timing
</div>

</div>

</div>

<div class="online">
<span class="dot"></span>
Server Online
</div>

</div>


<div class="stats">

<div class="stat">
<div class="sl">Total Sent</div>
<div id="total" class="sn">0</div>
</div>

<div class="stat">
<div class="sl">Opened</div>
<div id="opened" class="sn">0</div>
</div>

<div class="stat">
<div class="sl">Not Opened</div>
<div id="notopened" class="sn">0</div>
</div>

<div class="stat">
<div class="sl">Total Opens</div>
<div id="opens" class="sn">0</div>
</div>

</div>


<div class="grid">


<div class="card">

<div class="ct">
Send Email
</div>

<div class="cs">
Sender account is configured in app.py.
</div>

<div class="note">
<b>Sender:</b> configured at the top of app.py.<br>
<b>Password:</b> configured at the top of app.py.<br>
Recipients are entered below.<br><br>
Do NOT put your normal Gmail password in the code.
Use a Google App Password.
</div>


<label>
Recipients
</label>

<div id="users">

<div class="row">

<input
    class="recipient"
    type="email"
    placeholder="receiver@example.com"
>

<button
    class="remove"
    onclick="removeUser(this)"
>
×
</button>

</div>

</div>


<button
    class="add"
    onclick="addUser()"
>
+ Add Another User
</button>


<label>
Subject
</label>

<input
    id="subject"
    placeholder="Email subject"
>


<label>
Message
</label>

<textarea
    id="message"
    placeholder="Write your email..."
></textarea>


<button
    id="send"
    class="send"
    onclick="sendMail()"
>
SEND TO ALL USERS
</button>


<div
    id="result"
    class="result"
></div>

</div>


<div class="card">

<div class="tablehead">

<div>

<div class="ct">
Email Activity
</div>

<div class="cs">
Open timing is recorded when tracking image loads.
</div>

</div>

<button
    class="clear"
    onclick="clearData()"
>
Clear
</button>

</div>


<div class="tw">

<table>

<thead>

<tr>

<th>Sender</th>
<th>Recipient</th>
<th>Subject</th>
<th>Status</th>
<th>Sent</th>
<th>First Opened</th>
<th>Last Opened</th>
<th>Opens</th>
<th>Error</th>

</tr>

</thead>

<tbody id="body">
</tbody>

</table>

</div>

</div>

</div>

</div>


<script>

function addUser(){

    const d =
        document.createElement("div");

    d.className = "row";

    d.innerHTML =
        '<input class="recipient" ' +
        'type="email" ' +
        'placeholder="receiver@example.com">' +
        '<button class="remove" ' +
        'onclick="removeUser(this)">×</button>';

    document
        .getElementById("users")
        .appendChild(d);
}


function removeUser(button){

    const rows =
        document.querySelectorAll(".row");

    if(rows.length === 1){

        rows[0]
            .querySelector("input")
            .value = "";

        return;
    }

    button
        .closest(".row")
        .remove();
}


function recipients(){

    return [
        ...document.querySelectorAll(
            ".recipient"
        )
    ]
    .map(x => x.value.trim())
    .filter(Boolean);
}


function escapeHTML(value){

    const div =
        document.createElement("div");

    div.textContent =
        value ?? "";

    return div.innerHTML;
}


async function readJSON(response){

    const text =
        await response.text();

    try{

        return JSON.parse(text);

    }catch{

        return {
            success:false,
            error:
                "Server returned HTTP " +
                response.status +
                ": " +
                text.slice(0,300)
        };

    }

}


async function sendMail(){

    const rec =
        recipients();

    const subject =
        document
            .getElementById("subject")
            .value
            .trim();

    const message =
        document
            .getElementById("message")
            .value;

    const result =
        document
            .getElementById("result");

    const button =
        document
            .getElementById("send");


    if(
        !rec.length ||
        !subject ||
        !message.trim()
    ){

        result.style.color =
            "#f87171";

        result.textContent =
            "Recipient, subject aur message required.";

        return;

    }


    button.disabled = true;

    button.textContent =
        "SENDING...";

    result.style.color =
        "#aab5c6";

    result.textContent =
        "Sending to " +
        rec.length +
        " user(s)...";


    try{

        const response =
            await fetch(
                "/send",
                {
                    method:"POST",
                    headers:{
                        "Content-Type":
                            "application/json",
                        "Accept":
                            "application/json"
                    },
                    body:
                        JSON.stringify({
                            recipients:rec,
                            subject:subject,
                            message:message
                        })
                }
            );


        const data =
            await readJSON(response);


        if(data.sent > 0){

            result.style.color =
                "#4ade80";

            result.textContent =
                "✓ Sent: " +
                data.sent +
                " | Failed: " +
                data.failed;


            const failed =
                (data.results || [])
                .filter(x => !x.success);


            if(failed.length){

                result.textContent +=
                    "\n" +
                    failed
                    .map(
                        x =>
                        "❌ " +
                        x.recipient +
                        ": " +
                        x.error
                    )
                    .join("\n");

            }


            load();

        }else{

            result.style.color =
                "#f87171";

            result.textContent =
                "❌ " +
                (
                    data.error ||
                    "Sending failed."
                );


            load();

        }


    }catch(error){

        result.style.color =
            "#f87171";

        result.textContent =
            "❌ " +
            error.message;

    }


    finally{

        button.disabled = false;

        button.textContent =
            "SEND TO ALL USERS";

    }

}


function badge(status){

    const s =
        status ||
        "SENDING";

    const cls =
        s.toLowerCase();

    return (
        '<span class="badge ' +
        cls +
        '">' +
        '● ' +
        escapeHTML(s) +
        '</span>'
    );

}


async function load(){

    try{

        const response =
            await fetch(
                "/api/emails"
            );

        const data =
            await response.json();

        const body =
            document.getElementById(
                "body"
            );

        body.innerHTML = "";

        let opened = 0;
        let totalOpens = 0;


        data.forEach(email => {

            if(email.first_opened_at){
                opened++;
            }

            totalOpens +=
                Number(
                    email.open_count || 0
                );


            const row =
                document.createElement("tr");


            row.innerHTML =

                "<td>" +
                escapeHTML(email.sender) +
                "</td>" +

                "<td>" +
                escapeHTML(email.recipient) +
                "</td>" +

                "<td>" +
                escapeHTML(email.subject) +
                "</td>" +

                "<td>" +
                badge(email.status) +
                "</td>" +

                "<td>" +
                escapeHTML(
                    email.sent_at || "—"
                ) +
                "</td>" +

                "<td>" +
                escapeHTML(
                    email.first_opened_at ||
                    "—"
                ) +
                "</td>" +

                "<td>" +
                escapeHTML(
                    email.last_opened_at ||
                    "—"
                ) +
                "</td>" +

                "<td>" +
                Number(
                    email.open_count || 0
                ) +
                "</td>" +

                "<td class='err'>" +
                escapeHTML(
                    email.error || "—"
                ) +
                "</td>";


            body.appendChild(row);

        });


        if(!data.length){

            body.innerHTML =
                '<tr>' +
                '<td colspan="9" ' +
                'class="empty">' +
                'No emails sent yet' +
                '</td>' +
                '</tr>';

        }


        document
            .getElementById("total")
            .textContent =
            data.length;


        document
            .getElementById("opened")
            .textContent =
            opened;


        document
            .getElementById("notopened")
            .textContent =
            data.length - opened;


        document
            .getElementById("opens")
            .textContent =
            totalOpens;


    }catch(error){

        console.error(error);

    }

}


async function clearData(){

    if(
        !confirm(
            "Delete all tracking data?"
        )
    ){

        return;

    }


    await fetch(
        "/api/clear",
        {
            method:"POST"
        }
    );

    load();

}


load();

setInterval(
    load,
    3000
);

</script>

</body>

</html>
"""


# ============================================================
# START
# ============================================================
if __name__ == "__main__":

    init_db()

    print("")
    print("================================")
    print("MAIL SENDER & TRACKER")
    print("================================")
    print(
        "Sender:",
        SENDER_EMAIL
    )
    print(
        "Dashboard:",
        "http://127.0.0.1:5000"
    )
    print("================================")
    print("")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
