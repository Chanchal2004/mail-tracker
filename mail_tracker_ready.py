


import os
import re
import ssl
import uuid
import html
import json
import sqlite3
import smtplib
from datetime import datetime
from email.message import EmailMessage
from urllib.request import Request, urlopen

from flask import Flask, request, jsonify, Response, render_template_string

app = Flask(__name__)

# ============================================================
# SET THESE VALUES
# ============================================================

SENDER_EMAIL = "chanchal053btcse22@igdtuw.ac.in"
APP_PASSWORD = "dcompgffjspiflkv"

# YOUR RENDER URL - NO /track AT THE END:
RENDER_URL = "https://maill-trackkk.onrender.com"

# Put the SAME secret on Render and your PC.
TRACKER_SECRET = "MailTracker_2026_XYZ"

# ============================================================
# SETTINGS
# ============================================================

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
DB_PATH = "mail_tracker.db"

# ============================================================
# DATABASE
# ============================================================

def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            tracking_id TEXT PRIMARY KEY,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL,
            sent_at TEXT,
            first_opened_at TEXT,
            last_opened_at TEXT,
            open_count INTEGER DEFAULT 0,
            error TEXT DEFAULT ''
        )
    """)
    c.commit()
    c.close()

def now():
    return datetime.now().astimezone().strftime(
        "%d %b %Y, %I:%M:%S %p"
    )

def valid_email(value):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value or ""))

# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():
    return render_template_string(HTML)

# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():
    return jsonify(success=True, server="mail tracker")

# ============================================================
# RENDER: REGISTER SENT EMAIL
# ============================================================

@app.post("/api/register")
def register():
    secret = request.headers.get("X-Tracker-Secret", "")

    if secret != TRACKER_SECRET:
        return jsonify(success=False, error="Unauthorized"), 401

    data = request.get_json(silent=True) or {}

    tracking_id = str(data.get("tracking_id", "")).strip()
    sender = str(data.get("sender", "")).strip()
    recipient = str(data.get("recipient", "")).strip()
    subject = str(data.get("subject", "")).strip()
    sent_at = str(data.get("sent_at", "")).strip()

    if not all([tracking_id, sender, recipient, subject, sent_at]):
        return jsonify(
            success=False,
            error="Missing tracking data"
        ), 400

    c = db()
    c.execute("""
        INSERT OR REPLACE INTO emails
        (
            tracking_id, sender, recipient, subject,
            status, sent_at, first_opened_at,
            last_opened_at, open_count, error
        )
        VALUES (?, ?, ?, ?, 'SENT', ?, NULL, NULL, 0, '')
    """, (
        tracking_id,
        sender,
        recipient,
        subject,
        sent_at
    ))
    c.commit()
    c.close()

    return jsonify(success=True)

# ============================================================
# TRACK OPEN
# ============================================================

@app.get("/track/<tracking_id>")
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
                "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache"
        }
    )

# ============================================================
# TRACKING DATA
# ============================================================

@app.get("/api/emails")
def emails():
    c = db()
    rows = c.execute("""
        SELECT *
        FROM emails
        ORDER BY rowid DESC
    """).fetchall()
    c.close()

    return jsonify([dict(row) for row in rows])

@app.post("/api/clear")
def clear():
    c = db()
    c.execute("DELETE FROM emails")
    c.commit()
    c.close()
    return jsonify(success=True)

# ============================================================
# REGISTER SENT EMAIL ON RENDER
# ============================================================

def register_on_render(data):
    payload = json.dumps(data).encode("utf-8")

    req = Request(
        RENDER_URL.rstrip("/") + "/api/register",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Tracker-Secret": TRACKER_SECRET
        }
    )

    with urlopen(req, timeout=20) as response:
        return json.loads(
            response.read().decode("utf-8")
        )

# ============================================================
# SEND EMAIL FROM PC USING GMAIL SMTP
# ============================================================

@app.post("/send")
def send():
    sender = SENDER_EMAIL.strip()
    password = APP_PASSWORD.replace(" ", "").strip()

    data = request.get_json(silent=True) or {}

    recipient = str(
        data.get("recipient", "")
    ).strip()

    subject = str(
        data.get("subject", "")
    ).strip()

    message = str(
        data.get("message", "")
    )

    if not valid_email(sender):
        return jsonify(
            success=False,
            error="SENDER_EMAIL me apni Gmail ID daalo."
        ), 400

    if (
        not password or
        password == "PASTE_YOUR_16_DIGIT_APP_PASSWORD_HERE"
    ):
        return jsonify(
            success=False,
            error="APP_PASSWORD me Google App Password daalo."
        ), 400

    if not valid_email(recipient):
        return jsonify(
            success=False,
            error="Recipient email invalid hai."
        ), 400

    if not subject:
        return jsonify(
            success=False,
            error="Subject required hai."
        ), 400

    if not message.strip():
        return jsonify(
            success=False,
            error="Message required hai."
        ), 400

    tracking_id = uuid.uuid4().hex
    sent_at = now()

    tracking_url = (
        RENDER_URL.rstrip("/") +
        "/track/" +
        tracking_id
    )

    safe_message = (
        html.escape(message)
        .replace("\n", "<br>")
    )

    email_html = f"""
<!doctype html>
<html>
<body style="font-family:Arial,sans-serif;color:#222;line-height:1.6;">
    {safe_message}

    <img
        src="{html.escape(tracking_url, quote=True)}"
        width="1"
        height="1"
        alt=""
        style="display:block;border:0;"
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

    server = None

    try:
        server = smtplib.SMTP_SSL(
            SMTP_HOST,
            SMTP_PORT,
            context=ssl.create_default_context(),
            timeout=30
        )

        server.login(sender, password)
        server.send_message(msg)

    except Exception as e:
        return jsonify(
            success=False,
            sent=0,
            failed=1,
            error="SMTP failed: " + str(e)
        ), 400

    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass

    # Save the sent-mail record on Render.
    try:
        register_on_render({
            "tracking_id": tracking_id,
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "sent_at": sent_at
        })
    except Exception as e:
        return jsonify(
            success=True,
            sent=1,
            failed=0,
            tracking_id=tracking_id,
            warning=(
                "Mail sent, but Render registration failed: "
                + str(e)
            )
        )

    return jsonify(
        success=True,
        sent=1,
        failed=0,
        tracking_id=tracking_id,
        tracking_url=tracking_url
    )

# ============================================================
# DASHBOARD
# ============================================================

HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mail Sender & Tracker</title>
<style>
*{box-sizing:border-box}
body{
    margin:0;
    background:#080b12;
    color:#fff;
    font-family:Arial,sans-serif
}
.wrap{
    width:min(1400px,95%);
    margin:auto;
    padding:30px 0 60px
}
.grid{
    display:grid;
    grid-template-columns:360px 1fr;
    gap:20px
}
.card{
    background:#0d1421;
    border:1px solid #1d283b;
    border-radius:18px;
    padding:22px
}
h1{margin-top:0}
h2{font-size:18px}
.sub,.note{
    color:#8d99ad;
    font-size:12px;
    line-height:1.6
}
input,textarea{
    width:100%;
    padding:12px;
    margin:7px 0 15px;
    border:1px solid #2a374c;
    border-radius:9px;
    background:#070c14;
    color:white
}
textarea{min-height:150px}
button{
    width:100%;
    padding:13px;
    border:0;
    border-radius:9px;
    background:#536dfe;
    color:white;
    font-weight:bold;
    cursor:pointer
}
#result{
    margin-top:15px;
    font-size:12px;
    white-space:pre-wrap
}
.stats{
    display:grid;
    grid-template-columns:repeat(4,1fr);
    gap:12px;
    margin-bottom:20px
}
.stat{
    background:#0d1421;
    border:1px solid #1d283b;
    border-radius:14px;
    padding:16px
}
.num{font-size:27px;font-weight:800;margin-top:5px}
.label{font-size:10px;color:#8190a6}
.table{overflow:auto}
table{
    width:100%;
    min-width:1000px;
    border-collapse:collapse
}
th,td{
    padding:11px 8px;
    border-bottom:1px solid #1d283b;
    text-align:left;
    font-size:11px
}
th{color:#718096;font-size:10px}
.opened{
    color:#4ade80;
    background:#0d281a;
    padding:5px 8px;
    border-radius:15px
}
.sent{
    color:#93c5fd;
    background:#10203b;
    padding:5px 8px;
    border-radius:15px
}
.clear{
    width:auto;
    float:right;
    padding:8px 12px;
    background:#1b1015;
    border:1px solid #4a2a31
}
@media(max-width:950px){
    .grid{grid-template-columns:1fr}
    .stats{grid-template-columns:repeat(2,1fr)}
}
</style>
</head>

<body>
<div class="wrap">

<h1>✉ Mail Sender & Open Tracker</h1>
<div class="sub">
Gmail SMTP sends the mail from your PC.
Render receives the tracking request.
</div>

<br>

<div class="stats">
    <div class="stat">
        <div class="label">TOTAL SENT</div>
        <div class="num" id="total">0</div>
    </div>
    <div class="stat">
        <div class="label">OPENED</div>
        <div class="num" id="opened">0</div>
    </div>
    <div class="stat">
        <div class="label">NOT OPENED</div>
        <div class="num" id="notopened">0</div>
    </div>
    <div class="stat">
        <div class="label">TOTAL OPENS</div>
        <div class="num" id="opens">0</div>
    </div>
</div>

<div class="grid">

<div class="card">
    <h2>Send Email</h2>

    <label>Recipient</label>
    <input id="recipient"
           type="email"
           placeholder="receiver@example.com">

    <label>Subject</label>
    <input id="subject"
           placeholder="Email subject">

    <label>Message</label>
    <textarea id="message"
              placeholder="Write your message..."></textarea>

    <button id="send" onclick="sendMail()">
        SEND EMAIL
    </button>

    <div id="result"></div>
</div>

<div class="card">
    <button class="clear"
            onclick="clearData()">
        Clear
    </button>

    <h2>Email Activity</h2>

    <div class="table">
    <table>
        <thead>
            <tr>
                <th>Recipient</th>
                <th>Subject</th>
                <th>Status</th>
                <th>Sent</th>
                <th>First Opened</th>
                <th>Last Opened</th>
                <th>Opens</th>
            </tr>
        </thead>
        <tbody id="body"></tbody>
    </table>
    </div>
</div>

</div>
</div>

<script>
function esc(v){
    const d=document.createElement("div");
    d.textContent=v ?? "";
    return d.innerHTML;
}

async function sendMail(){
    const recipient=document.getElementById("recipient").value.trim();
    const subject=document.getElementById("subject").value.trim();
    const message=document.getElementById("message").value;
    const result=document.getElementById("result");
    const button=document.getElementById("send");

    if(!recipient || !subject || !message.trim()){
        result.style.color="#f87171";
        result.textContent="Recipient, subject aur message required.";
        return;
    }

    button.disabled=true;
    button.textContent="SENDING...";
    result.style.color="#aab5c6";
    result.textContent="Sending...";

    try{
        const response=await fetch("/send",{
            method:"POST",
            headers:{
                "Content-Type":"application/json"
            },
            body:JSON.stringify({
                recipient,
                subject,
                message
            })
        });

        const data=await response.json();

        if(data.success){
            result.style.color="#4ade80";
            result.textContent =
                "✓ Mail sent!\n"+
                "Tracking ID: "+data.tracking_id+
                (data.warning ? "\nWARNING: "+data.warning : "");
            load();
        }else{
            result.style.color="#f87171";
            result.textContent="❌ "+(data.error || "Failed");
        }

    }catch(e){
        result.style.color="#f87171";
        result.textContent="❌ "+e.message;
    }

    button.disabled=false;
    button.textContent="SEND EMAIL";
}

async function load(){
    try{
        const r=await fetch("/api/emails");
        const data=await r.json();

        let opened=0;
        let totalOpens=0;

        const body=document.getElementById("body");
        body.innerHTML="";

        data.forEach(e=>{
            if(e.first_opened_at) opened++;
            totalOpens += Number(e.open_count || 0);

            const tr=document.createElement("tr");

            tr.innerHTML =
                "<td>"+esc(e.recipient)+"</td>"+
                "<td>"+esc(e.subject)+"</td>"+
                "<td><span class='"+(
                    e.status==="OPENED" ? "opened" : "sent"
                )+"'>"+esc(e.status)+"</span></td>"+
                "<td>"+esc(e.sent_at || "—")+"</td>"+
                "<td>"+esc(e.first_opened_at || "—")+"</td>"+
                "<td>"+esc(e.last_opened_at || "—")+"</td>"+
                "<td>"+Number(e.open_count || 0)+"</td>";

            body.appendChild(tr);
        });

        document.getElementById("total").textContent=data.length;
        document.getElementById("opened").textContent=opened;
        document.getElementById("notopened").textContent=data.length-opened;
        document.getElementById("opens").textContent=totalOpens;

    }catch(e){
        console.error(e);
    }
}

async function clearData(){
    if(!confirm("Delete all tracking data?")) return;

    await fetch("/api/clear",{
        method:"POST"
    });

    load();
}

load();
setInterval(load,3000);
</script>
</body>
</html>
"""

# ============================================================
# START
# ============================================================

init_db()

if __name__ == "__main__":
    print()
    print("======================================")
    print("MAIL SENDER + OPEN TRACKER")
    print("======================================")
    print("Dashboard: http://127.0.0.1:5000")
    print("Render tracker:", RENDER_URL)
    print("SMTP:", SMTP_HOST, SMTP_PORT)
    print("======================================")
    print()

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False
    )
