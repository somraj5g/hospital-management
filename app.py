import sqlite3
from datetime import date, datetime

from jinja2 import FunctionLoader
from flask import Flask, flash, redirect, render_template, request, url_for

from database import get_connection, init_db

app = Flask(__name__, static_folder=None)
app.jinja_loader = FunctionLoader(lambda name: TEMPLATES.get(name))


@app.context_processor
def inject_css():
    return {"CSS": CSS}

app.secret_key = "change-this-secret-key"
init_db()


@app.template_filter("money")
def money(value):
    return f"₹{float(value):,.2f}"


def to_float(value, default=0.0):
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return default


APPT_QUERY = """
SELECT a.id, a.date, a.time, a.status,
       p.name AS patient, d.name AS doctor, d.specialization,
       b.id AS bill_id, b.status AS bill_status
FROM appointments a
JOIN patients p ON p.id = a.patient_id
JOIN doctors  d ON d.id = a.doctor_id
LEFT JOIN bills b ON b.appointment_id = a.id
"""


# ---------------------------------------------------------------- Dashboard
@app.route("/")
def dashboard():
    today = date.today().isoformat()
    conn = get_connection()
    one = lambda q, p=(): conn.execute(q, p).fetchone()[0]
    stats = {
        "patients": one("SELECT COUNT(*) FROM patients"),
        "doctors": one("SELECT COUNT(*) FROM doctors"),
        "today": one("SELECT COUNT(*) FROM appointments WHERE date=? AND status='Scheduled'", (today,)),
        "unpaid": one("SELECT COALESCE(SUM(total),0) FROM bills WHERE status='Unpaid'"),
        "revenue": one("SELECT COALESCE(SUM(total),0) FROM bills WHERE status='Paid'"),
    }
    upcoming = conn.execute(
        APPT_QUERY + " WHERE a.status='Scheduled' AND a.date>=? ORDER BY a.date, a.time LIMIT 8",
        (today,),
    ).fetchall()
    conn.close()
    return render_template("index.html", stats=stats, upcoming=upcoming)


# ----------------------------------------------------------------- Patients
@app.route("/patients")
def patients():
    q = request.args.get("q", "").strip()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM patients WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    conn.close()
    return render_template("patients.html", rows=rows, q=q)


@app.route("/patients/add", methods=["GET", "POST"])
def patient_add():
    if request.method == "POST":
        f = request.form
        conn = get_connection()
        conn.execute(
            "INSERT INTO patients (name, age, gender, phone, address) VALUES (?,?,?,?,?)",
            (f["name"].strip(), int(f["age"]), f["gender"], f["phone"].strip(), f["address"].strip()),
        )
        conn.commit()
        conn.close()
        flash("Patient added successfully.", "success")
        return redirect(url_for("patients"))
    return render_template("patient_form.html", p=None)


@app.route("/patients/<int:pid>/edit", methods=["GET", "POST"])
def patient_edit(pid):
    conn = get_connection()
    p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        flash("Patient not found.", "error")
        return redirect(url_for("patients"))
    if request.method == "POST":
        f = request.form
        conn.execute(
            "UPDATE patients SET name=?, age=?, gender=?, phone=?, address=? WHERE id=?",
            (f["name"].strip(), int(f["age"]), f["gender"], f["phone"].strip(), f["address"].strip(), pid),
        )
        conn.commit()
        conn.close()
        flash("Patient updated.", "success")
        return redirect(url_for("patients"))
    conn.close()
    return render_template("patient_form.html", p=p)


@app.route("/patients/<int:pid>/delete", methods=["POST"])
def patient_delete(pid):
    conn = get_connection()
    conn.execute("DELETE FROM patients WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    flash("Patient deleted.", "success")
    return redirect(url_for("patients"))


# ------------------------------------------------------------------ Doctors
@app.route("/doctors")
def doctors():
    q = request.args.get("q", "").strip()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM doctors WHERE name LIKE ? OR specialization LIKE ? ORDER BY id DESC",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    conn.close()
    return render_template("doctors.html", rows=rows, q=q)


@app.route("/doctors/add", methods=["GET", "POST"])
def doctor_add():
    if request.method == "POST":
        f = request.form
        conn = get_connection()
        conn.execute(
            "INSERT INTO doctors (name, specialization, phone, fee) VALUES (?,?,?,?)",
            (f["name"].strip(), f["specialization"].strip(), f["phone"].strip(), to_float(f["fee"])),
        )
        conn.commit()
        conn.close()
        flash("Doctor added successfully.", "success")
        return redirect(url_for("doctors"))
    return render_template("doctor_form.html", d=None)


@app.route("/doctors/<int:did>/edit", methods=["GET", "POST"])
def doctor_edit(did):
    conn = get_connection()
    d = conn.execute("SELECT * FROM doctors WHERE id=?", (did,)).fetchone()
    if not d:
        conn.close()
        flash("Doctor not found.", "error")
        return redirect(url_for("doctors"))
    if request.method == "POST":
        f = request.form
        conn.execute(
            "UPDATE doctors SET name=?, specialization=?, phone=?, fee=? WHERE id=?",
            (f["name"].strip(), f["specialization"].strip(), f["phone"].strip(), to_float(f["fee"]), did),
        )
        conn.commit()
        conn.close()
        flash("Doctor updated.", "success")
        return redirect(url_for("doctors"))
    conn.close()
    return render_template("doctor_form.html", d=d)


@app.route("/doctors/<int:did>/delete", methods=["POST"])
def doctor_delete(did):
    conn = get_connection()
    conn.execute("DELETE FROM doctors WHERE id=?", (did,))
    conn.commit()
    conn.close()
    flash("Doctor deleted.", "success")
    return redirect(url_for("doctors"))


# ------------------------------------------------------------- Appointments
@app.route("/appointments")
def appointments():
    status = request.args.get("status", "")
    day = request.args.get("date", "")
    sql, params, where = APPT_QUERY, [], []
    if status:
        where.append("a.status = ?")
        params.append(status)
    if day:
        where.append("a.date = ?")
        params.append(day)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY a.date DESC, a.time DESC"
    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template("appointments.html", rows=rows, status=status, day=day)


@app.route("/appointments/book", methods=["GET", "POST"])
def appointment_add():
    conn = get_connection()
    patients_ = conn.execute("SELECT id, name, phone FROM patients ORDER BY name").fetchall()
    doctors_ = conn.execute("SELECT id, name, specialization, fee FROM doctors ORDER BY name").fetchall()
    today = date.today().isoformat()

    if request.method == "POST":
        f = request.form
        try:
            if datetime.strptime(f["date"], "%Y-%m-%d").date() < date.today():
                flash("Past date la appointment book panna mudiyadhu.", "error")
            else:
                conn.execute(
                    "INSERT INTO appointments (patient_id, doctor_id, date, time) VALUES (?,?,?,?)",
                    (f["patient_id"], f["doctor_id"], f["date"], f["time"]),
                )
                conn.commit()
                flash("Appointment booked successfully.", "success")
                conn.close()
                return redirect(url_for("appointments"))
        except sqlite3.IntegrityError:
            flash("Andha doctor ku andha time la already appointment irukku. Vera time select pannunga.", "error")
    conn.close()
    return render_template("appointment_form.html", patients=patients_, doctors=doctors_, today=today)


@app.route("/appointments/<int:aid>/<action>", methods=["POST"])
def appointment_status(aid, action):
    new_status = {"complete": "Completed", "cancel": "Cancelled"}.get(action)
    if not new_status:
        return redirect(url_for("appointments"))
    conn = get_connection()
    conn.execute(
        "UPDATE appointments SET status=? WHERE id=? AND status='Scheduled'", (new_status, aid)
    )
    conn.commit()
    conn.close()
    flash(f"Appointment marked as {new_status}.", "success")
    return redirect(request.referrer or url_for("appointments"))


# ------------------------------------------------------------------ Billing
@app.route("/bills")
def bills():
    status = request.args.get("status", "")
    sql = """
        SELECT b.id, b.total, b.status, b.created_at, a.date,
               p.name AS patient, d.name AS doctor
        FROM bills b
        JOIN appointments a ON a.id = b.appointment_id
        JOIN patients p ON p.id = a.patient_id
        JOIN doctors  d ON d.id = a.doctor_id
    """
    params = []
    if status:
        sql += " WHERE b.status = ?"
        params.append(status)
    sql += " ORDER BY b.id DESC"
    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template("bills.html", rows=rows, status=status)


@app.route("/bills/generate/<int:aid>", methods=["GET", "POST"])
def bill_generate(aid):
    conn = get_connection()
    a = conn.execute(
        """SELECT a.id, a.date, a.time, a.status, p.name AS patient,
                  d.name AS doctor, d.specialization, d.fee
           FROM appointments a
           JOIN patients p ON p.id = a.patient_id
           JOIN doctors  d ON d.id = a.doctor_id WHERE a.id=?""",
        (aid,),
    ).fetchone()

    if not a:
        conn.close()
        flash("Appointment not found.", "error")
        return redirect(url_for("appointments"))
    if a["status"] != "Completed":
        conn.close()
        flash("Completed appointments ku mattum bill generate pannalam.", "error")
        return redirect(url_for("appointments"))
    existing = conn.execute("SELECT id FROM bills WHERE appointment_id=?", (aid,)).fetchone()
    if existing:
        conn.close()
        flash("Indha appointment ku already bill irukku.", "error")
        return redirect(url_for("invoice", bid=existing["id"]))

    if request.method == "POST":
        medicine = to_float(request.form.get("medicine"))
        other = to_float(request.form.get("other"))
        total = a["fee"] + medicine + other
        cur = conn.execute(
            "INSERT INTO bills (appointment_id, consultation_fee, medicine_charges, other_charges, total)"
            " VALUES (?,?,?,?,?)",
            (aid, a["fee"], medicine, other, total),
        )
        conn.commit()
        bid = cur.lastrowid
        conn.close()
        flash("Bill generated.", "success")
        return redirect(url_for("invoice", bid=bid))

    conn.close()
    return render_template("bill_form.html", a=a)


@app.route("/bills/<int:bid>/pay", methods=["POST"])
def bill_pay(bid):
    conn = get_connection()
    conn.execute("UPDATE bills SET status='Paid' WHERE id=?", (bid,))
    conn.commit()
    conn.close()
    flash("Payment received. Bill marked as Paid.", "success")
    return redirect(request.referrer or url_for("bills"))


@app.route("/bills/<int:bid>")
def invoice(bid):
    conn = get_connection()
    b = conn.execute(
        """SELECT b.*, a.date, a.time, p.name AS patient, p.phone AS patient_phone,
                  p.age, p.gender, d.name AS doctor, d.specialization
           FROM bills b
           JOIN appointments a ON a.id = b.appointment_id
           JOIN patients p ON p.id = a.patient_id
           JOIN doctors  d ON d.id = a.doctor_id WHERE b.id=?""",
        (bid,),
    ).fetchone()
    conn.close()
    if not b:
        flash("Bill not found.", "error")
        return redirect(url_for("bills"))
    return render_template("invoice.html", b=b)

# =====================================================================
#  HTML TEMPLATES + CSS (ella inga irukku, templates/static folder thevai illa)
# =====================================================================

TEMPLATES = {
    'appointment_form.html': r'''{% extends "base.html" %}
{% block title %}Book Appointment{% endblock %}
{% block content %}
<h1>Book Appointment</h1>
<p class="sub">Select patient, doctor, date and time</p>
<div class="panel form-card">
  {% if not patients or not doctors %}
    <div class="empty">
      Appointment book panna muthalla
      {% if not patients %}<a href="{{ url_for('patient_add') }}">oru patient</a>{% endif %}
      {% if not patients and not doctors %} and {% endif %}
      {% if not doctors %}<a href="{{ url_for('doctor_add') }}">oru doctor</a>{% endif %}
      add pannunga.
    </div>
  {% else %}
  <form method="post">
    <div class="field"><label>Patient</label>
      <select name="patient_id" required>
        <option value="">-- Select Patient --</option>
        {% for p in patients %}<option value="{{ p.id }}">{{ p.name }} ({{ p.phone }})</option>{% endfor %}
      </select>
    </div>
    <div class="field"><label>Doctor</label>
      <select name="doctor_id" required>
        <option value="">-- Select Doctor --</option>
        {% for d in doctors %}<option value="{{ d.id }}">Dr. {{ d.name }} - {{ d.specialization }} ({{ d.fee|money }})</option>{% endfor %}
      </select>
    </div>
    <div class="row2">
      <div class="field"><label>Date</label><input type="date" name="date" min="{{ today }}" required></div>
      <div class="field"><label>Time</label><input type="time" name="time" required></div>
    </div>
    <div class="actions"><button class="btn">Book Appointment</button><a class="btn gray" href="{{ url_for('appointments') }}">Cancel</a></div>
  </form>
  {% endif %}
</div>
{% endblock %}
''',

    'appointments.html': r'''{% extends "base.html" %}
{% block title %}Appointments{% endblock %}
{% block content %}
<div class="topbar">
  <div><h1>Appointments</h1><p class="sub" style="margin:0">{{ rows|length }} record(s)</p></div>
  <div class="actions">
    <form class="filters" method="get">
      <select name="status">
        <option value="">All Status</option>
        {% for s in ['Scheduled', 'Completed', 'Cancelled'] %}<option {{ 'selected' if status == s }}>{{ s }}</option>{% endfor %}
      </select>
      <input type="date" name="date" value="{{ day }}">
      <button class="btn gray">Filter</button>
      <a class="btn gray" href="{{ url_for('appointments') }}">Reset</a>
    </form>
    <a class="btn" href="{{ url_for('appointment_add') }}">+ Book Appointment</a>
  </div>
</div>
<div class="panel">
  {% if rows %}
  <table>
    <tr><th>ID</th><th>Patient</th><th>Doctor</th><th>Date</th><th>Time</th><th>Status</th><th>Actions</th></tr>
    {% for a in rows %}
    <tr>
      <td>#{{ a.id }}</td><td><b>{{ a.patient }}</b></td>
      <td>Dr. {{ a.doctor }}<br><small style="color:var(--muted)">{{ a.specialization }}</small></td>
      <td>{{ a.date }}</td><td>{{ a.time }}</td>
      <td><span class="badge b-{{ a.status }}">{{ a.status }}</span></td>
      <td class="actions">
        {% if a.status == 'Scheduled' %}
          <form method="post" action="{{ url_for('appointment_status', aid=a.id, action='complete') }}"><button class="btn sm green">Complete</button></form>
          <form method="post" action="{{ url_for('appointment_status', aid=a.id, action='cancel') }}" onsubmit="return confirm('Cancel this appointment?')"><button class="btn sm red">Cancel</button></form>
        {% elif a.status == 'Completed' %}
          {% if a.bill_id %}
            <a class="btn sm gray" href="{{ url_for('invoice', bid=a.bill_id) }}">View Bill</a>
          {% else %}
            <a class="btn sm orange" href="{{ url_for('bill_generate', aid=a.id) }}">Generate Bill</a>
          {% endif %}
        {% else %}-{% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}<div class="empty">No appointments found.</div>{% endif %}
</div>
{% endblock %}
''',

    'base.html': r'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Dashboard{% endblock %} | MediCare HMS</title>
  <style>{{ CSS|safe }}</style>
</head>
<body>
  {% set ep = request.endpoint or '' %}
  <aside class="sidebar">
    <div class="brand">🏥 MediCare HMS</div>
    <a href="{{ url_for('dashboard') }}" class="{{ 'active' if ep == 'dashboard' }}">📊 Dashboard</a>
    <a href="{{ url_for('patients') }}" class="{{ 'active' if ep.startswith('patient') }}">🧑 Patients</a>
    <a href="{{ url_for('doctors') }}" class="{{ 'active' if ep.startswith('doctor') }}">🩺 Doctors</a>
    <a href="{{ url_for('appointments') }}" class="{{ 'active' if ep.startswith('appointment') }}">📅 Appointments</a>
    <a href="{{ url_for('bills') }}" class="{{ 'active' if ep.startswith('bill') or ep == 'invoice' }}">💳 Billing</a>
  </aside>
  <main>
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for cat, msg in messages %}<div class="flash {{ cat }}">{{ msg }}</div>{% endfor %}
    {% endwith %}
    {% block content %}{% endblock %}
  </main>
</body>
</html>
''',

    'bill_form.html': r'''{% extends "base.html" %}
{% block title %}Generate Bill{% endblock %}
{% block content %}
<h1>Generate Bill</h1>
<p class="sub">Appointment #{{ a.id }} - {{ a.patient }} with Dr. {{ a.doctor }} ({{ a.date }} {{ a.time }})</p>
<div class="panel form-card">
  <form method="post">
    <div class="field"><label>Consultation Fee (Doctor fee)</label><input value="{{ a.fee }}" disabled></div>
    <div class="row2">
      <div class="field"><label>Medicine Charges (₹)</label><input type="number" step="0.01" min="0" name="medicine" id="med" value="0"></div>
      <div class="field"><label>Other Charges (₹)</label><input type="number" step="0.01" min="0" name="other" id="oth" value="0"></div>
    </div>
    <h2>Total: <span id="total">{{ a.fee|money }}</span></h2>
    <div class="actions"><button class="btn">Generate Bill</button><a class="btn gray" href="{{ url_for('appointments') }}">Cancel</a></div>
  </form>
</div>
<script>
  const fee = {{ a.fee }};
  const med = document.getElementById('med'), oth = document.getElementById('oth'), tot = document.getElementById('total');
  function calc() {
    const t = fee + (parseFloat(med.value) || 0) + (parseFloat(oth.value) || 0);
    tot.textContent = '₹' + t.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }
  med.addEventListener('input', calc); oth.addEventListener('input', calc);
</script>
{% endblock %}
''',

    'bills.html': r'''{% extends "base.html" %}
{% block title %}Billing{% endblock %}
{% block content %}
<div class="topbar">
  <div><h1>Billing</h1><p class="sub" style="margin:0">{{ rows|length }} bill(s)</p></div>
  <form class="filters" method="get">
    <select name="status" onchange="this.form.submit()">
      <option value="">All Bills</option>
      {% for s in ['Unpaid', 'Paid'] %}<option {{ 'selected' if status == s }}>{{ s }}</option>{% endfor %}
    </select>
  </form>
</div>
<div class="panel">
  {% if rows %}
  <table>
    <tr><th>Bill</th><th>Patient</th><th>Doctor</th><th>Visit Date</th><th>Total</th><th>Status</th><th>Actions</th></tr>
    {% for b in rows %}
    <tr>
      <td>#{{ b.id }}</td><td><b>{{ b.patient }}</b></td><td>Dr. {{ b.doctor }}</td>
      <td>{{ b.date }}</td><td><b>{{ b.total|money }}</b></td>
      <td><span class="badge b-{{ b.status }}">{{ b.status }}</span></td>
      <td class="actions">
        <a class="btn sm gray" href="{{ url_for('invoice', bid=b.id) }}">Invoice</a>
        {% if b.status == 'Unpaid' %}
        <form method="post" action="{{ url_for('bill_pay', bid=b.id) }}" onsubmit="return confirm('Mark this bill as paid?')"><button class="btn sm green">Mark Paid</button></form>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <div class="empty">No bills yet. Appointment ah "Complete" pannitu, <a href="{{ url_for('appointments') }}">Appointments</a> page la "Generate Bill" click pannunga.</div>
  {% endif %}
</div>
{% endblock %}
''',

    'doctor_form.html': r'''{% extends "base.html" %}
{% block title %}{{ 'Edit' if d else 'Add' }} Doctor{% endblock %}
{% block content %}
<h1>{{ 'Edit Doctor' if d else 'Add Doctor' }}</h1>
<p class="sub">Doctor details</p>
<div class="panel form-card">
  <form method="post">
    <div class="field"><label>Full Name</label><input name="name" required value="{{ d.name if d }}"></div>
    <div class="field"><label>Specialization</label><input name="specialization" required value="{{ d.specialization if d }}"></div>
    <div class="row2">
      <div class="field"><label>Phone</label><input name="phone" required value="{{ d.phone if d }}"></div>
      <div class="field"><label>Consultation Fee (₹)</label><input type="number" step="0.01" min="0" name="fee" required value="{{ d.fee if d }}"></div>
    </div>
    <div class="actions"><button class="btn">Save</button><a class="btn gray" href="{{ url_for('doctors') }}">Cancel</a></div>
  </form>
</div>
{% endblock %}
''',

    'doctors.html': r'''{% extends "base.html" %}
{% block title %}Doctors{% endblock %}
{% block content %}
<div class="topbar">
  <div><h1>Doctors</h1><p class="sub" style="margin:0">{{ rows|length }} record(s)</p></div>
  <div class="actions">
    <form class="filters" method="get">
      <input name="q" value="{{ q }}" placeholder="Search name / specialization">
      <button class="btn gray">Search</button>
    </form>
    <a class="btn" href="{{ url_for('doctor_add') }}">+ Add Doctor</a>
  </div>
</div>
<div class="panel">
  {% if rows %}
  <table>
    <tr><th>ID</th><th>Name</th><th>Specialization</th><th>Phone</th><th>Fee</th><th>Actions</th></tr>
    {% for d in rows %}
    <tr>
      <td>#{{ d.id }}</td><td><b>Dr. {{ d.name }}</b></td><td>{{ d.specialization }}</td>
      <td>{{ d.phone }}</td><td>{{ d.fee|money }}</td>
      <td class="actions">
        <a class="btn sm gray" href="{{ url_for('doctor_edit', did=d.id) }}">Edit</a>
        <form method="post" action="{{ url_for('doctor_delete', did=d.id) }}"
              onsubmit="return confirm('Delete this doctor? Related appointments and bills will also be deleted.')">
          <button class="btn sm red">Delete</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}<div class="empty">No doctors found.</div>{% endif %}
</div>
{% endblock %}
''',

    'index.html': r'''{% extends "base.html" %}
{% block title %}Dashboard{% endblock %}
{% block content %}
<h1>Dashboard</h1>
<p class="sub">Hospital overview</p>

<div class="cards">
  <div class="stat"><div class="num">{{ stats.patients }}</div><div class="lbl">Total Patients</div></div>
  <div class="stat"><div class="num">{{ stats.doctors }}</div><div class="lbl">Total Doctors</div></div>
  <div class="stat"><div class="num">{{ stats.today }}</div><div class="lbl">Today's Appointments</div></div>
  <div class="stat warn"><div class="num">{{ stats.unpaid|money }}</div><div class="lbl">Unpaid Bills</div></div>
  <div class="stat ok"><div class="num">{{ stats.revenue|money }}</div><div class="lbl">Revenue (Paid)</div></div>
</div>

<div class="panel">
  <h2>Upcoming Appointments</h2>
  {% if upcoming %}
  <table>
    <tr><th>ID</th><th>Patient</th><th>Doctor</th><th>Date</th><th>Time</th><th>Status</th></tr>
    {% for a in upcoming %}
    <tr>
      <td>#{{ a.id }}</td><td>{{ a.patient }}</td><td>Dr. {{ a.doctor }}</td>
      <td>{{ a.date }}</td><td>{{ a.time }}</td><td><span class="badge b-{{ a.status }}">{{ a.status }}</span></td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <div class="empty">Upcoming appointments illa. <a href="{{ url_for('appointment_add') }}">Book one</a></div>
  {% endif %}
</div>
{% endblock %}
''',

    'invoice.html': r'''{% extends "base.html" %}
{% block title %}Invoice #{{ b.id }}{% endblock %}
{% block content %}
<div class="panel invoice">
  <div class="head">
    <h2>🏥 MediCare Hospital</h2>
    <div style="color:var(--muted)">INVOICE</div>
  </div>
  <dl>
    <dt>Bill No</dt><dd>#{{ b.id }}</dd>
    <dt>Bill Date</dt><dd>{{ b.created_at }}</dd>
    <dt>Patient</dt><dd>{{ b.patient }} ({{ b.age }}, {{ b.gender }})</dd>
    <dt>Phone</dt><dd>{{ b.patient_phone }}</dd>
    <dt>Doctor</dt><dd>Dr. {{ b.doctor }} - {{ b.specialization }}</dd>
    <dt>Visit</dt><dd>{{ b.date }} {{ b.time }}</dd>
  </dl>
  <div class="line"><span>Consultation Fee</span><span>{{ b.consultation_fee|money }}</span></div>
  <div class="line"><span>Medicine Charges</span><span>{{ b.medicine_charges|money }}</span></div>
  <div class="line"><span>Other Charges</span><span>{{ b.other_charges|money }}</span></div>
  <div class="line total"><span>TOTAL</span><span>{{ b.total|money }}</span></div>
  <p style="text-align:center;margin:16px 0 0"><span class="badge b-{{ b.status }}" style="font-size:14px;padding:6px 18px">{{ b.status }}</span></p>
  <div class="actions no-print" style="margin-top:22px;justify-content:center">
    <button class="btn" onclick="window.print()">🖨 Print</button>
    {% if b.status == 'Unpaid' %}
    <form method="post" action="{{ url_for('bill_pay', bid=b.id) }}"><button class="btn green">Mark as Paid</button></form>
    {% endif %}
    <a class="btn gray" href="{{ url_for('bills') }}">Back</a>
  </div>
</div>
{% endblock %}
''',

    'patient_form.html': r'''{% extends "base.html" %}
{% block title %}{{ 'Edit' if p else 'Add' }} Patient{% endblock %}
{% block content %}
<h1>{{ 'Edit Patient' if p else 'Add Patient' }}</h1>
<p class="sub">Patient details</p>
<div class="panel form-card">
  <form method="post">
    <div class="field"><label>Full Name</label><input name="name" required value="{{ p.name if p }}"></div>
    <div class="row2">
      <div class="field"><label>Age</label><input type="number" name="age" min="0" max="120" required value="{{ p.age if p }}"></div>
      <div class="field"><label>Gender</label>
        <select name="gender">
          {% for g in ['Male', 'Female', 'Other'] %}<option {{ 'selected' if p and p.gender == g }}>{{ g }}</option>{% endfor %}
        </select>
      </div>
    </div>
    <div class="field"><label>Phone</label><input name="phone" required value="{{ p.phone if p }}"></div>
    <div class="field"><label>Address</label><textarea name="address" rows="3">{{ p.address if p and p.address }}</textarea></div>
    <div class="actions"><button class="btn">Save</button><a class="btn gray" href="{{ url_for('patients') }}">Cancel</a></div>
  </form>
</div>
{% endblock %}
''',

    'patients.html': r'''{% extends "base.html" %}
{% block title %}Patients{% endblock %}
{% block content %}
<div class="topbar">
  <div><h1>Patients</h1><p class="sub" style="margin:0">{{ rows|length }} record(s)</p></div>
  <div class="actions">
    <form class="filters" method="get">
      <input name="q" value="{{ q }}" placeholder="Search name / phone">
      <button class="btn gray">Search</button>
    </form>
    <a class="btn" href="{{ url_for('patient_add') }}">+ Add Patient</a>
  </div>
</div>
<div class="panel">
  {% if rows %}
  <table>
    <tr><th>ID</th><th>Name</th><th>Age</th><th>Gender</th><th>Phone</th><th>Address</th><th>Actions</th></tr>
    {% for p in rows %}
    <tr>
      <td>#{{ p.id }}</td><td><b>{{ p.name }}</b></td><td>{{ p.age }}</td><td>{{ p.gender }}</td>
      <td>{{ p.phone }}</td><td>{{ p.address or '-' }}</td>
      <td class="actions">
        <a class="btn sm gray" href="{{ url_for('patient_edit', pid=p.id) }}">Edit</a>
        <form method="post" action="{{ url_for('patient_delete', pid=p.id) }}"
              onsubmit="return confirm('Delete this patient? Related appointments and bills will also be deleted.')">
          <button class="btn sm red">Delete</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}<div class="empty">No patients found.</div>{% endif %}
</div>
{% endblock %}
''',

}

CSS = r''':root {
  --bg: #f3f6f9; --card: #ffffff; --text: #1e2a35; --muted: #6b7a89;
  --primary: #0d9488; --primary-dark: #0f766e; --side: #0f2e3d;
  --danger: #dc2626; --warn: #d97706; --ok: #16a34a; --border: #e2e8f0;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); display: flex; min-height: 100vh; }
.sidebar { width: 230px; background: var(--side); color: #cfe3ec; padding: 24px 14px; position: sticky; top: 0; height: 100vh; flex-shrink: 0; }
.brand { font-size: 20px; font-weight: 700; color: #fff; padding: 0 10px 24px; display: flex; align-items: center; gap: 8px; }
.sidebar a { display: block; color: #cfe3ec; text-decoration: none; padding: 11px 14px; border-radius: 8px; margin-bottom: 4px; font-size: 15px; }
.sidebar a:hover { background: rgba(255,255,255,.08); }
.sidebar a.active { background: var(--primary); color: #fff; }
main { flex: 1; padding: 28px 34px; min-width: 0; }
h1 { margin: 0 0 4px; font-size: 26px; }
.sub { color: var(--muted); margin: 0 0 22px; }
.topbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 16px; margin-bottom: 26px; }
.stat { background: var(--card); border-radius: 12px; padding: 18px; border: 1px solid var(--border); border-left: 5px solid var(--primary); }
.stat .num { font-size: 28px; font-weight: 700; }
.stat .lbl { color: var(--muted); font-size: 13px; }
.stat.warn { border-left-color: var(--warn); } .stat.ok { border-left-color: var(--ok); }
.panel { background: var(--card); border-radius: 12px; border: 1px solid var(--border); padding: 20px; overflow-x: auto; }
.panel h2 { margin: 0 0 14px; font-size: 18px; }
table { width: 100%; border-collapse: collapse; font-size: 14.5px; }
th { text-align: left; color: var(--muted); font-weight: 600; font-size: 12.5px; text-transform: uppercase; letter-spacing: .04em; padding: 10px 12px; border-bottom: 2px solid var(--border); }
td { padding: 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f8fafc; }
.empty { text-align: center; color: var(--muted); padding: 34px 0; }
.btn { display: inline-block; background: var(--primary); color: #fff; border: none; padding: 9px 16px; border-radius: 8px; font-size: 14px; cursor: pointer; text-decoration: none; font-family: inherit; }
.btn:hover { background: var(--primary-dark); }
.btn.sm { padding: 5px 11px; font-size: 13px; }
.btn.gray { background: #64748b; } .btn.red { background: var(--danger); }
.btn.green { background: var(--ok); } .btn.orange { background: var(--warn); }
.actions { display: flex; gap: 6px; flex-wrap: wrap; }
.actions form { margin: 0; }
.badge { padding: 3px 10px; border-radius: 99px; font-size: 12px; font-weight: 600; }
.b-Scheduled { background: #dbeafe; color: #1d4ed8; } .b-Completed { background: #dcfce7; color: #15803d; }
.b-Cancelled { background: #fee2e2; color: #b91c1c; } .b-Paid { background: #dcfce7; color: #15803d; }
.b-Unpaid { background: #fef3c7; color: #b45309; }
.flash { padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 14.5px; }
.flash.success { background: #dcfce7; color: #166534; } .flash.error { background: #fee2e2; color: #991b1b; }
form.filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
input, select, textarea { padding: 9px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14.5px; font-family: inherit; background: #fff; }
input:focus, select:focus, textarea:focus { outline: 2px solid rgba(13,148,136,.35); border-color: var(--primary); }
.form-card { max-width: 620px; }
.field { margin-bottom: 16px; display: flex; flex-direction: column; gap: 6px; }
.field label { font-weight: 600; font-size: 14px; }
.row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.invoice { max-width: 640px; margin: 0 auto; }
.invoice .head { text-align: center; border-bottom: 2px dashed var(--border); padding-bottom: 14px; margin-bottom: 14px; }
.invoice .head h2 { margin: 0; color: var(--primary-dark); }
.invoice dl { display: grid; grid-template-columns: 140px 1fr; gap: 8px; margin: 0 0 14px; }
.invoice dt { color: var(--muted); } .invoice dd { margin: 0; font-weight: 600; }
.invoice .line { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border); }
.invoice .total { font-size: 20px; font-weight: 700; border-bottom: none; border-top: 2px solid var(--text); margin-top: 6px; }
@media (max-width: 800px) {
  body { flex-direction: column; }
  .sidebar { width: 100%; height: auto; position: static; display: flex; flex-wrap: wrap; gap: 4px; padding: 12px; }
  .brand { width: 100%; padding-bottom: 8px; } main { padding: 18px; } .row2 { grid-template-columns: 1fr; }
}
@media print {
  .sidebar, .no-print, .flash { display: none !important; } body { background: #fff; }
  main { padding: 0; } .panel { border: none; }
}
'''


if __name__ == "__main__":
    app.run(debug=True)