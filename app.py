from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
from datetime import datetime
import calendar
import smtplib
import os
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps

app = Flask(__name__)
app.secret_key = os.urandom(24)

DB_PATH = os.path.join(os.path.dirname(__file__), "attendance.db")


# ─────────────────────────────────────────────
#  DB INIT
# ─────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript(open(os.path.join(os.path.dirname(__file__), "schema.sql")).read())
    conn.commit()
    conn.close()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


# ─────────────────────────────────────────────
#  AUTH DECORATOR
# ─────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "teacher_id" not in session:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def generate_month(year, month, teacher_id):
    conn = get_conn()
    c = conn.cursor()
    today = datetime.today()
    c.execute(
        "SELECT holiday_date FROM holidays WHERE teacher_id=? OR teacher_id IS NULL",
        (teacher_id,)
    )
    holidays = {row[0] for row in c.fetchall()}
    conn.close()

    num_days = calendar.monthrange(int(year), int(month))[1]
    dates = []
    for day in range(1, num_days + 1):
        d = datetime(int(year), int(month), day)
        date_str = d.strftime("%Y-%m-%d")
        if d > today:
            break
        if d.weekday() == 6 or date_str in holidays:
            dates.append((date_str, "H"))
        else:
            dates.append((date_str, "W"))
    return dates


def load_matrix(year, month, class_id, teacher_id):
    conn = get_conn()
    c = conn.cursor()
    dates = generate_month(year, month, teacher_id)
    c.execute("SELECT id, name FROM students WHERE class_id=?", (class_id,))
    students = c.fetchall()
    rows = []
    for s in students:
        sid, name = s["id"], s["name"]
        row = {"Student": name}
        total = present = 0
        for date_str, dtype in dates:
            if dtype == "H":
                row[date_str] = "H"
                continue
            c.execute("SELECT status FROM attendance WHERE student_id=? AND date=?", (sid, date_str))
            r = c.fetchone()
            val = float(r[0]) if r else 1
            row[date_str] = val
            total += 1
            present += val
        row["attendance_percent"] = round(present / total * 100, 1) if total else 0
        rows.append(row)
    conn.close()
    return rows, [d[0] for d in dates], [d[1] for d in dates]


def build_email(name, percent, month_name, year):
    if percent >= 90:
        subject = f"🌟 Excellent Attendance – {month_name} {year}"
        color = "#16a34a"; badge_bg = "#dcfce7"; badge_color = "#15803d"
        badge = "EXCELLENT"
        headline = f"Outstanding work, {name.split()[0]}!"
        message = "Your attendance has been truly exemplary this month. You're setting a fantastic example for your peers."
        tip = "🎯 Pro tip: Consistent attendance is one of the strongest predictors of academic success!"
        footer_note = "Keep soaring high!"
    elif percent >= 75:
        subject = f"📊 Attendance Update – {month_name} {year}"
        color = "#d97706"; badge_bg = "#fef3c7"; badge_color = "#b45309"
        badge = "GOOD"
        headline = f"You're doing well, {name.split()[0]}!"
        message = "Your attendance is in a good place, but there's still room to push it higher."
        tip = "📈 Just a few more classes can significantly improve your percentage."
        footer_note = "Keep pushing forward!"
    else:
        subject = f"⚠️ Attendance Alert – {month_name} {year} [Action Required]"
        color = "#dc2626"; badge_bg = "#fee2e2"; badge_color = "#b91c1c"
        badge = "LOW ATTENDANCE"
        headline = f"Urgent attention needed, {name.split()[0]}"
        message = "Your attendance has fallen below the required threshold. Please meet your class coordinator immediately."
        tip = "🚨 Action required: Please visit the coordinator's office at your earliest convenience."
        footer_note = "We're here to help — please reach out."

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f4f5;margin:0;padding:0}}
.wrapper{{max-width:600px;margin:40px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
.header{{background:{color};padding:40px 36px 32px;color:#fff}}
.header h1{{margin:0 0 4px;font-size:26px;font-weight:700}}
.header p{{margin:0;opacity:.85;font-size:14px}}
.body{{padding:36px}}
.badge{{display:inline-block;background:{badge_bg};color:{badge_color};font-size:11px;font-weight:700;letter-spacing:1.5px;padding:4px 12px;border-radius:20px;margin-bottom:20px}}
.percent-box{{background:#f8fafc;border:2px solid {color};border-radius:12px;padding:24px;text-align:center;margin:24px 0}}
.percent-num{{font-size:56px;font-weight:800;color:{color};line-height:1}}
.percent-label{{color:#64748b;font-size:14px;margin-top:4px}}
.message{{color:#374151;font-size:15px;line-height:1.7;margin:20px 0}}
.tip-box{{background:#f1f5f9;border-left:4px solid {color};border-radius:0 8px 8px 0;padding:14px 18px;font-size:14px;color:#475569;margin:24px 0}}
.footer{{background:#f8fafc;border-top:1px solid #e2e8f0;padding:24px 36px;text-align:center;color:#94a3b8;font-size:13px}}
.footer strong{{color:#64748b}}
</style></head><body>
<div class="wrapper">
  <div class="header"><h1>🎓 RACE REVA</h1><p>Attendance Report — {month_name} {year}</p></div>
  <div class="body">
    <span class="badge">{badge}</span>
    <h2 style="margin:0 0 8px;color:#111827;font-size:22px;">{headline}</h2>
    <p class="message">{message}</p>
    <div class="percent-box">
      <div class="percent-num">{percent}%</div>
      <div class="percent-label">Attendance this month</div>
    </div>
    <div class="tip-box">{tip}</div>
  </div>
  <div class="footer"><strong>RACE REVA Attendance System</strong><br>{footer_note} · This is an automated notification.</div>
</div></body></html>"""
    return subject, html


# ─────────────────────────────────────────────
#  AUTH ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    if "teacher_id" not in session:
        return redirect(url_for("login_page"))
    return render_template("index.html")


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name, username FROM teachers WHERE username=? AND password=?",
              (data["username"], hash_pw(data["password"])))
    teacher = c.fetchone()
    conn.close()
    if teacher:
        session["teacher_id"] = teacher["id"]
        session["teacher_name"] = teacher["name"]
        session["teacher_username"] = teacher["username"]
        return jsonify({"status": "ok", "name": teacher["name"]})
    return jsonify({"status": "error", "message": "Invalid username or password"}), 401


@app.route("/api/auth/register", methods=["POST"])
def api_register():
    data = request.json
    if not data.get("name") or not data.get("username") or not data.get("password"):
        return jsonify({"status": "error", "message": "All fields required"}), 400
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO teachers (name, username, password) VALUES (?,?,?)",
                  (data["name"], data["username"], hash_pw(data["password"])))
        conn.commit()
        tid = c.lastrowid
        session["teacher_id"] = tid
        session["teacher_name"] = data["name"]
        session["teacher_username"] = data["username"]
        conn.close()
        return jsonify({"status": "ok", "name": data["name"]})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"status": "error", "message": "Username already taken"}), 409


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"status": "ok"})


@app.route("/api/auth/me", methods=["GET"])
def api_me():
    if "teacher_id" not in session:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({
        "id": session["teacher_id"],
        "name": session["teacher_name"],
        "username": session["teacher_username"]
    })


# ─────────────────────────────────────────────
#  EMAIL SETTINGS (per teacher)
# ─────────────────────────────────────────────

@app.route("/api/email-settings/get", methods=["GET"])
@login_required
def api_get_email_settings():
    tid = session["teacher_id"]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT email, app_password FROM teacher_email_settings WHERE teacher_id=?", (tid,))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({"email": row["email"], "saved": True})
    return jsonify({"email": "", "saved": False})


@app.route("/api/email-settings/save", methods=["POST"])
@login_required
def api_save_email_settings():
    tid = session["teacher_id"]
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO teacher_email_settings (teacher_id, email, app_password) VALUES (?,?,?)
                 ON CONFLICT(teacher_id) DO UPDATE SET email=excluded.email, app_password=excluded.app_password""",
              (tid, data["email"], data["app_password"]))
    conn.commit()
    conn.close()
    return jsonify({"status": "saved"})


# ─────────────────────────────────────────────
#  CLASSES ROUTES
# ─────────────────────────────────────────────

@app.route("/api/classes", methods=["GET"])
@login_required
def api_get_classes():
    tid = session["teacher_id"]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name, section, subject FROM classes WHERE teacher_id=? ORDER BY name", (tid,))
    classes = [{"id": r["id"], "name": r["name"], "section": r["section"], "subject": r["subject"]}
               for r in c.fetchall()]
    conn.close()
    return jsonify({"classes": classes})


@app.route("/api/classes/add", methods=["POST"])
@login_required
def api_add_class():
    tid = session["teacher_id"]
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO classes (teacher_id, name, section, subject) VALUES (?,?,?,?)",
              (tid, data["name"], data.get("section", ""), data.get("subject", "")))
    conn.commit()
    cid = c.lastrowid
    conn.close()
    return jsonify({"status": "added", "id": cid})


@app.route("/api/classes/delete", methods=["POST"])
@login_required
def api_delete_class():
    tid = session["teacher_id"]
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    # Verify ownership
    c.execute("SELECT id FROM classes WHERE id=? AND teacher_id=?", (data["id"], tid))
    if not c.fetchone():
        conn.close()
        return jsonify({"status": "error"}), 403
    c.execute("DELETE FROM classes WHERE id=?", (data["id"],))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


@app.route("/api/classes/update", methods=["POST"])
@login_required
def api_update_class():
    tid = session["teacher_id"]
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE classes SET name=?, section=?, subject=? WHERE id=? AND teacher_id=?",
              (data["name"], data.get("section", ""), data.get("subject", ""), data["id"], tid))
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})


# ─────────────────────────────────────────────
#  STUDENTS ROUTES (class-scoped)
# ─────────────────────────────────────────────

def verify_class_ownership(class_id):
    """Returns True if current teacher owns class_id"""
    tid = session.get("teacher_id")
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM classes WHERE id=? AND teacher_id=?", (class_id, tid))
    r = c.fetchone()
    conn.close()
    return r is not None


@app.route("/api/students", methods=["GET"])
@login_required
def api_get_students():
    class_id = request.args.get("class_id")
    if not class_id or not verify_class_ownership(class_id):
        return jsonify({"error": "forbidden"}), 403
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name, email FROM students WHERE class_id=? ORDER BY name", (class_id,))
    students = [{"id": r["id"], "name": r["name"], "email": r["email"]} for r in c.fetchall()]
    conn.close()
    return jsonify({"students": students})


@app.route("/api/students/add", methods=["POST"])
@login_required
def api_add_student():
    data = request.json
    class_id = data["class_id"]
    if not verify_class_ownership(class_id):
        return jsonify({"error": "forbidden"}), 403
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO students (class_id, name, email) VALUES (?,?,?)",
                  (class_id, data["name"], data["email"]))
        conn.commit()
        conn.close()
        return jsonify({"status": "added"})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"status": "error", "message": "Email already exists in this class"}), 409


@app.route("/api/students/update", methods=["POST"])
@login_required
def api_update_students():
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    for s in data["students"]:
        c.execute("UPDATE students SET name=?, email=? WHERE id=?", (s["name"], s["email"], s["id"]))
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})


@app.route("/api/students/delete", methods=["POST"])
@login_required
def api_delete_student():
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM students WHERE id=?", (data["id"],))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


# ─────────────────────────────────────────────
#  ATTENDANCE ROUTES
# ─────────────────────────────────────────────

@app.route("/api/attendance/load", methods=["POST"])
@login_required
def api_load_attendance():
    data = request.json
    class_id = data["class_id"]
    if not verify_class_ownership(class_id):
        return jsonify({"error": "forbidden"}), 403
    rows, dates, dtypes = load_matrix(data["year"], data["month"], class_id, session["teacher_id"])
    return jsonify({"rows": rows, "dates": dates, "dtypes": dtypes})


@app.route("/api/attendance/save", methods=["POST"])
@login_required
def api_save_attendance():
    data = request.json
    class_id = data["class_id"]
    if not verify_class_ownership(class_id):
        return jsonify({"error": "forbidden"}), 403
    tid = session["teacher_id"]
    conn = get_conn()
    c = conn.cursor()
    dates = generate_month(data["year"], data["month"], tid)
    c.execute("SELECT id, name FROM students WHERE class_id=?", (class_id,))
    student_map = {r["name"]: r["id"] for r in c.fetchall()}
    for row in data["rows"]:
        name = row["Student"]
        if name not in student_map:
            continue
        sid = student_map[name]
        for date_str, dtype in dates:
            if dtype == "H":
                continue
            if date_str in row:
                c.execute("""INSERT INTO attendance (student_id, date, status) VALUES (?,?,?)
                             ON CONFLICT(student_id,date) DO UPDATE SET status=excluded.status""",
                          (sid, date_str, float(row[date_str])))
    conn.commit()
    conn.close()
    return jsonify({"status": "saved"})


@app.route("/api/absentees", methods=["POST"])
@login_required
def api_absentees():
    data = request.json
    class_id = data["class_id"]
    if not verify_class_ownership(class_id):
        return jsonify({"error": "forbidden"}), 403
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name FROM students WHERE class_id=?", (class_id,))
    students = c.fetchall()
    absentees = []
    for s in students:
        c.execute("SELECT status FROM attendance WHERE student_id=? AND date=?", (s["id"], data["date"]))
        r = c.fetchone()
        if not r or float(r["status"]) == 0:
            absentees.append(s["name"])
    conn.close()
    return jsonify({"absentees": absentees})


@app.route("/api/report", methods=["POST"])
@login_required
def api_report():
    data = request.json
    class_id = data["class_id"]
    if not verify_class_ownership(class_id):
        return jsonify({"error": "forbidden"}), 403
    tid = session["teacher_id"]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM students WHERE class_id=? AND name=?", (class_id, data["student"]))
    r = c.fetchone()
    if not r:
        conn.close()
        return jsonify({"rows": [], "percent": 0})
    sid = r["id"]
    dates = generate_month(data["year"], data["month"], tid)
    rows = []
    total = present = 0
    for date_str, dtype in dates:
        if dtype == "H":
            continue
        c.execute("SELECT status FROM attendance WHERE student_id=? AND date=?", (sid, date_str))
        r2 = c.fetchone()
        if r2 and float(r2["status"]) == 1:
            status = "Present"; present += 1
        else:
            status = "Absent"
        total += 1
        rows.append({"date": date_str, "status": status})
    percent = round(present / total * 100, 2) if total else 0
    conn.close()
    return jsonify({"rows": rows, "percent": percent})


@app.route("/api/low-attendance", methods=["POST"])
@login_required
def api_low_attendance():
    data = request.json
    class_id = data["class_id"]
    if not verify_class_ownership(class_id):
        return jsonify({"error": "forbidden"}), 403
    tid = session["teacher_id"]
    threshold = data.get("threshold", 85)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name, email FROM students WHERE class_id=?", (class_id,))
    students = c.fetchall()
    dates = generate_month(data["year"], data["month"], tid)
    result = []
    for s in students:
        total = present = 0
        for date_str, dtype in dates:
            if dtype == "H":
                continue
            c.execute("SELECT status FROM attendance WHERE student_id=? AND date=?", (s["id"], date_str))
            r = c.fetchone()
            total += 1
            present += float(r["status"]) if r else 1
        percent = round(present / total * 100, 1) if total else 0
        if percent < threshold:
            result.append({"id": s["id"], "name": s["name"], "email": s["email"], "percent": percent})
    conn.close()
    result.sort(key=lambda x: x["percent"])
    return jsonify({"students": result})


# ─────────────────────────────────────────────
#  EMAIL ROUTES
# ─────────────────────────────────────────────

def get_teacher_smtp(teacher_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT email, app_password FROM teacher_email_settings WHERE teacher_id=?", (teacher_id,))
    row = c.fetchone()
    conn.close()
    return (row["email"], row["app_password"]) if row else (None, None)


@app.route("/api/email/preview", methods=["POST"])
@login_required
def api_email_preview():
    data = request.json
    class_id = data["class_id"]
    if not verify_class_ownership(class_id):
        return jsonify({"error": "forbidden"}), 403
    tid = session["teacher_id"]
    conn = get_conn()
    c = conn.cursor()
    if data.get("student_id"):
        c.execute("SELECT id, name, email FROM students WHERE id=? AND class_id=?", (data["student_id"], class_id))
    else:
        c.execute("SELECT id, name, email FROM students WHERE class_id=?", (class_id,))
    students = c.fetchall()
    dates = generate_month(data["year"], data["month"], tid)
    working = [d for d, t in dates if t != "H"]
    previews = []
    for s in students:
        total = len(working)
        present = sum(
            float((c.execute("SELECT status FROM attendance WHERE student_id=? AND date=?",
                              (s["id"], ds)).fetchone() or (1,))[0])
            for ds in working
        )
        percent = round(present / total * 100, 1) if total else 0
        previews.append({"id": s["id"], "name": s["name"], "email": s["email"], "percent": percent})
    conn.close()
    return jsonify({"previews": previews})


@app.route("/api/email/send", methods=["POST"])
@login_required
def api_send_email():
    data = request.json
    class_id = data["class_id"]
    if not verify_class_ownership(class_id):
        return jsonify({"error": "forbidden"}), 403
    tid = session["teacher_id"]
    email_user, email_pass = get_teacher_smtp(tid)
    if not email_user:
        return jsonify({"status": "error", "message": "Email not configured. Please save your email settings first."}), 400

    month_name = calendar.month_name[int(data["month"])]
    conn = get_conn()
    c = conn.cursor()
    if data.get("student_id"):
        c.execute("SELECT id, name, email FROM students WHERE id=? AND class_id=?", (data["student_id"], class_id))
    else:
        c.execute("SELECT id, name, email FROM students WHERE class_id=?", (class_id,))
    students = c.fetchall()
    dates = generate_month(data["year"], data["month"], tid)
    working = [d for d, t in dates if t != "H"]

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(email_user, email_pass)
        sent = 0
        for s in students:
            total = len(working)
            present = 0
            for ds in working:
                c.execute("SELECT status FROM attendance WHERE student_id=? AND date=?", (s["id"], ds))
                r = c.fetchone()
                present += float(r["status"]) if r else 1
            percent = round(present / total * 100, 1) if total else 0
            subject, body = build_email(s["name"], percent, month_name, data["year"])
            msg = MIMEMultipart("alternative")
            msg["From"] = email_user
            msg["To"] = s["email"]
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html"))
            server.send_message(msg)
            sent += 1
        server.quit()
        conn.close()
        return jsonify({"status": "sent", "count": sent})
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)})


# ─────────────────────────────────────────────
#  HOLIDAYS
# ─────────────────────────────────────────────

@app.route("/api/holidays/add", methods=["POST"])
@login_required
def api_add_holiday():
    tid = session["teacher_id"]
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO holidays (teacher_id, holiday_date, reason) VALUES (?,?,?)",
              (tid, data["date"], data.get("reason", "")))
    conn.commit()
    conn.close()
    return jsonify({"status": "added"})


@app.route("/api/holidays/remove", methods=["POST"])
@login_required
def api_remove_holiday():
    tid = session["teacher_id"]
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM holidays WHERE holiday_date=? AND teacher_id=?", (data["date"], tid))
    conn.commit()
    conn.close()
    return jsonify({"status": "removed"})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
