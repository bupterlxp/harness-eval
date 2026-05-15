#!/usr/bin/env python3
"""
mock_server.py — Mock HR Management System
A self-contained Flask app simulating an enterprise HR portal.
Used as the target environment for the browser agent harness eval.
"""
import csv
import io
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, g, jsonify, make_response, redirect, render_template,
    request, session, url_for,
)

app = Flask(__name__, template_folder="templates")
app.secret_key = "harness-eval-mock-secret-key-2024"
DB_PATH = os.environ.get("MOCK_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "hr_mock.db"))

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'employee'
    );
    CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        gender TEXT,
        department_id INTEGER REFERENCES departments(id),
        position TEXT,
        email TEXT,
        phone TEXT,
        hire_date TEXT,
        status TEXT DEFAULT 'active',
        annual_leave_balance REAL DEFAULT 10.0,
        performance_score REAL DEFAULT 0.0
    );
    CREATE TABLE IF NOT EXISTS leave_requests (
        id INTEGER PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id),
        leave_type TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        reason TEXT,
        emergency_contact TEXT,
        status TEXT DEFAULT 'pending',
        reviewer TEXT,
        review_comment TEXT,
        created_at TEXT,
        reviewed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY,
        department_id INTEGER REFERENCES departments(id),
        month TEXT,
        total_staff INTEGER,
        avg_attendance_rate REAL,
        late_count INTEGER,
        early_leave_count INTEGER,
        absent_count INTEGER
    );
    """)
    db.commit()


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

DEPARTMENTS = ["技术部", "产品部", "市场部", "人力资源部", "财务部"]

LAST_NAMES = "张王李赵刘陈杨黄周吴徐孙马朱胡郭何林罗高"
FIRST_NAMES_M = "伟强磊军勇杰涛明辉鑫斌波峰宇飞鹏程昊然"
FIRST_NAMES_F = "芳娟敏静丽艳娜秀英华慧婷雪琳晶萍倩颖玲"

POSITIONS = {
    "技术部": ["高级工程师", "中级工程师", "初级工程师", "技术经理", "架构师", "测试工程师"],
    "产品部": ["产品经理", "高级产品经理", "产品助理", "用户研究员", "数据分析师"],
    "市场部": ["市场经理", "品牌专员", "活动策划", "新媒体运营", "市场分析师"],
    "人力资源部": ["HR经理", "招聘专员", "薪酬专员", "培训专员", "HRBP"],
    "财务部": ["财务经理", "会计", "出纳", "审计专员", "税务专员"],
}


def seed_data():
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return

    db.execute("INSERT INTO users VALUES (1,'admin','admin123','系统管理员','admin')")
    db.execute("INSERT INTO users VALUES (2,'user01','user123','张三','employee')")
    db.commit()

    for i, name in enumerate(DEPARTMENTS, 1):
        db.execute("INSERT INTO departments VALUES (?,?)", (i, name))
    db.commit()

    random.seed(42)
    employees = []
    eid = 1
    for dept_id, dept_name in enumerate(DEPARTMENTS, 1):
        count = 10
        positions = POSITIONS[dept_name]
        for j in range(count):
            gender = random.choice(["男", "女"])
            last = random.choice(LAST_NAMES)
            first = random.choice(FIRST_NAMES_M if gender == "男" else FIRST_NAMES_F)
            if len(first) == 1 and random.random() > 0.5:
                first += random.choice(FIRST_NAMES_M if gender == "男" else FIRST_NAMES_F)
            name = last + first[:2]
            pos = positions[j % len(positions)]
            hire_year = random.randint(2016, 2023)
            hire_month = random.randint(1, 12)
            hire_date = f"{hire_year}-{hire_month:02d}-{random.randint(1,28):02d}"
            email = f"emp{eid:03d}@company.com"
            phone = f"138{random.randint(10000000,99999999)}"
            status = "active" if random.random() > 0.06 else "inactive"
            leave_bal = round(random.uniform(2, 15), 1)
            perf = round(random.uniform(60, 98), 1)
            db.execute(
                "INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (eid, name, gender, dept_id, pos, email, phone, hire_date, status, leave_bal, perf),
            )
            employees.append(eid)
            eid += 1

    extra_zhang = [
        ("张伟", "男", 1, "高级工程师", "2021-03-15", 8.5, 85.2),
        ("张敏", "女", 2, "产品经理", "2019-07-22", 5.0, 78.9),
        ("张涛", "男", 3, "市场经理", "2022-11-08", 12.0, 91.3),
        ("张静", "女", 4, "招聘专员", "2020-06-01", 9.5, 82.7),
    ]
    for name, gender, dept_id, pos, hd, lb, perf in extra_zhang:
        db.execute(
            "INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (eid, name, gender, dept_id, pos, f"emp{eid:03d}@company.com",
             f"138{random.randint(10000000,99999999)}", hd, "active", lb, perf),
        )
        employees.append(eid)
        eid += 1

    today = datetime.now()
    recent_hires = [
        ("周明", "男", 1, "初级工程师", (today - timedelta(days=10)).strftime("%Y-%m-%d"), 10.0, 0.0),
        ("陈雪", "女", 2, "产品助理", (today - timedelta(days=5)).strftime("%Y-%m-%d"), 10.0, 0.0),
        ("李波", "男", 5, "会计", (today - timedelta(days=18)).strftime("%Y-%m-%d"), 10.0, 0.0),
    ]
    for name, gender, dept_id, pos, hd, lb, perf in recent_hires:
        db.execute(
            "INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (eid, name, gender, dept_id, pos, f"emp{eid:03d}@company.com",
             f"138{random.randint(10000000,99999999)}", hd, "active", lb, perf),
        )
        employees.append(eid)
        eid += 1

    db.commit()

    leave_types = ["年假", "病假", "事假"]
    base = datetime(2024, 1, 10)
    for i in range(1, 16):
        emp_id = random.choice(employees)
        lt = random.choice(leave_types)
        start = base + timedelta(days=random.randint(0, 40))
        duration = random.randint(1, 5)
        end = start + timedelta(days=duration)
        reason = random.choice(["身体不适", "家庭原因", "个人事务", "出行计划", "回老家", "看病复查", "亲友婚礼", "搬家"])
        emergency = f"紧急联系人{random.choice(LAST_NAMES)}: 139{random.randint(10000000,99999999)}"
        status = "pending" if i <= 8 else random.choice(["approved", "rejected"])
        created = (start - timedelta(days=random.randint(1, 7))).strftime("%Y-%m-%d %H:%M")
        reviewed_at = None
        reviewer = None
        review_comment = None
        if status != "pending":
            reviewer = "admin"
            reviewed_at = (start - timedelta(days=random.randint(0, 2))).strftime("%Y-%m-%d %H:%M")
            if status == "rejected":
                review_comment = "当前项目进度紧张，建议另选时间"
        db.execute(
            "INSERT INTO leave_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, emp_id, lt, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
             reason, emergency, status, reviewer, review_comment, created, reviewed_at),
        )
    db.commit()

    for dept_id in range(1, 6):
        for month_offset in range(3):
            m = f"2024-{month_offset+1:02d}"
            db.execute(
                "INSERT INTO attendance (department_id,month,total_staff,avg_attendance_rate,late_count,early_leave_count,absent_count) VALUES (?,?,?,?,?,?,?)",
                (dept_id, m, 10, round(random.uniform(92, 99), 1),
                 random.randint(0, 8), random.randint(0, 5), random.randint(0, 3)),
            )
    db.commit()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "未登录"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "权限不足"}), 403
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Simulated latency
# ---------------------------------------------------------------------------

@app.before_request
def simulate_latency():
    if request.path.startswith("/api/") and request.path != "/api/login":
        time.sleep(random.uniform(0.15, 0.4))


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard_page"))
    return redirect(url_for("login_page"))


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard_page():
    return render_template("dashboard.html", user=session.get("display_name"))


@app.route("/employees")
@login_required
def employees_page():
    return render_template("employees.html")


@app.route("/employees/<int:eid>")
@login_required
def employee_detail_page(eid):
    return render_template("employee_detail.html", employee_id=eid)


@app.route("/leave-requests")
@login_required
def leave_requests_page():
    return render_template("leave_requests.html", role=session.get("role"))


@app.route("/leave/new")
@login_required
def leave_form_page():
    return render_template("leave_form.html")


@app.route("/reports")
@login_required
def reports_page():
    return render_template("reports.html")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    username = data.get("username", "")
    password = data.get("password", "")
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE username=? AND password=?", (username, password)
    ).fetchone()
    if not user:
        return jsonify({"error": "用户名或密码错误"}), 401
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["display_name"] = user["display_name"]
    session["role"] = user["role"]
    return jsonify({"message": "登录成功", "user": {"id": user["id"], "name": user["display_name"], "role": user["role"]}})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"message": "已退出"})


@app.route("/api/dashboard")
@login_required
def api_dashboard():
    db = get_db()
    pending = db.execute("SELECT COUNT(*) FROM leave_requests WHERE status='pending'").fetchone()[0]
    new_hires = db.execute("SELECT COUNT(*) FROM employees WHERE hire_date >= date('now','-30 days')").fetchone()[0]
    expiring = db.execute("SELECT COUNT(*) FROM employees WHERE hire_date <= date('now','-2555 days') AND status='active'").fetchone()[0]
    total_emp = db.execute("SELECT COUNT(*) FROM employees WHERE status='active'").fetchone()[0]
    return jsonify({
        "pending_leaves": pending,
        "new_hires": new_hires,
        "contract_expiring": max(expiring, 1),
        "total_employees": total_emp,
    })


@app.route("/api/employees")
@login_required
def api_employees():
    db = get_db()
    dept = request.args.get("department", "")
    search = request.args.get("search", "")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 10))

    sql = """SELECT e.*, d.name as department_name
             FROM employees e JOIN departments d ON e.department_id=d.id WHERE 1=1"""
    params = []
    if dept:
        sql += " AND d.name=?"
        params.append(dept)
    if search:
        sql += " AND (e.name LIKE ? OR e.email LIKE ? OR e.position LIKE ?)"
        params.extend([f"%{search}%"] * 3)

    total = db.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
    sql += " ORDER BY e.id LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    rows = db.execute(sql, params).fetchall()
    return jsonify({
        "employees": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    })


@app.route("/api/employees/<int:eid>")
@login_required
def api_employee_detail(eid):
    db = get_db()
    emp = db.execute(
        "SELECT e.*, d.name as department_name FROM employees e JOIN departments d ON e.department_id=d.id WHERE e.id=?", (eid,)
    ).fetchone()
    if not emp:
        return jsonify({"error": "员工不存在"}), 404
    leaves = db.execute(
        "SELECT * FROM leave_requests WHERE employee_id=? ORDER BY created_at DESC", (eid,)
    ).fetchall()
    return jsonify({"employee": dict(emp), "leave_history": [dict(r) for r in leaves]})


@app.route("/api/leave-requests")
@login_required
def api_leave_requests():
    db = get_db()
    status_filter = request.args.get("status", "")
    sql = """SELECT lr.*, e.name as employee_name, d.name as department_name
             FROM leave_requests lr
             JOIN employees e ON lr.employee_id=e.id
             JOIN departments d ON e.department_id=d.id"""
    params = []
    if status_filter:
        sql += " WHERE lr.status=?"
        params.append(status_filter)
    sql += " ORDER BY lr.created_at DESC"
    rows = db.execute(sql, params).fetchall()
    return jsonify({"leave_requests": [dict(r) for r in rows], "total": len(rows)})


@app.route("/api/leave-requests", methods=["POST"])
@login_required
def api_create_leave():
    data = request.get_json(force=True)
    required = ["leave_type", "start_date", "end_date", "reason"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"缺少必填字段: {field}"}), 400
    if data["leave_type"] not in ("年假", "病假", "事假"):
        return jsonify({"error": "无效的请假类型"}), 400
    try:
        s = datetime.strptime(data["start_date"], "%Y-%m-%d")
        e = datetime.strptime(data["end_date"], "%Y-%m-%d")
        if e < s:
            return jsonify({"error": "结束日期不能早于开始日期"}), 400
    except ValueError:
        return jsonify({"error": "日期格式不正确"}), 400

    db = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor = db.execute(
        "INSERT INTO leave_requests (employee_id,leave_type,start_date,end_date,reason,emergency_contact,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (1, data["leave_type"], data["start_date"], data["end_date"], data["reason"], data.get("emergency_contact", ""), "pending", now),
    )
    db.commit()
    return jsonify({"message": "请假申请已提交", "id": cursor.lastrowid}), 201


@app.route("/api/leave-requests/<int:lid>/approve", methods=["POST"])
@login_required
@admin_required
def api_approve_leave(lid):
    db = get_db()
    lr = db.execute("SELECT * FROM leave_requests WHERE id=?", (lid,)).fetchone()
    if not lr:
        return jsonify({"error": "请假记录不存在"}), 404
    if lr["status"] != "pending":
        return jsonify({"error": "该请假已处理"}), 400
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    db.execute(
        "UPDATE leave_requests SET status='approved', reviewer=?, reviewed_at=? WHERE id=?",
        (session["username"], now, lid),
    )
    db.commit()
    return jsonify({"message": "已批准"})


@app.route("/api/leave-requests/<int:lid>/reject", methods=["POST"])
@login_required
@admin_required
def api_reject_leave(lid):
    data = request.get_json(force=True) if request.is_json else {}
    db = get_db()
    lr = db.execute("SELECT * FROM leave_requests WHERE id=?", (lid,)).fetchone()
    if not lr:
        return jsonify({"error": "请假记录不存在"}), 404
    if lr["status"] != "pending":
        return jsonify({"error": "该请假已处理"}), 400
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    db.execute(
        "UPDATE leave_requests SET status='rejected', reviewer=?, review_comment=?, reviewed_at=? WHERE id=?",
        (session["username"], data.get("comment", ""), now, lid),
    )
    db.commit()
    return jsonify({"message": "已拒绝"})


@app.route("/api/reports/attendance")
@login_required
def api_attendance():
    db = get_db()
    rows = db.execute(
        "SELECT a.*, d.name as department_name FROM attendance a JOIN departments d ON a.department_id=d.id ORDER BY a.month, d.id"
    ).fetchall()
    return jsonify({"attendance": [dict(r) for r in rows]})


@app.route("/api/reports/export")
@login_required
def api_export():
    db = get_db()
    rows = db.execute(
        "SELECT d.name as department, a.month, a.total_staff, a.avg_attendance_rate, a.late_count, a.early_leave_count, a.absent_count "
        "FROM attendance a JOIN departments d ON a.department_id=d.id ORDER BY a.month, d.id"
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["部门", "月份", "总人数", "平均出勤率(%)", "迟到次数", "早退次数", "缺勤次数"])
    for r in rows:
        writer.writerow([r["department"], r["month"], r["total_staff"], r["avg_attendance_rate"], r["late_count"], r["early_leave_count"], r["absent_count"]])
    resp = make_response(output.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=attendance_report.csv"
    return resp


@app.route("/api/departments")
@login_required
def api_departments():
    db = get_db()
    rows = db.execute("SELECT * FROM departments ORDER BY id").fetchall()
    return jsonify({"departments": [dict(r) for r in rows]})


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

with app.app_context():
    if os.path.exists(DB_PATH) and DB_PATH != ":memory:":
        os.remove(DB_PATH)
    init_db()
    seed_data()

if __name__ == "__main__":
    print("Mock HR System running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
