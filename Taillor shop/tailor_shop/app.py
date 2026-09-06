import os
import smtplib
from functools import wraps
from email.message import EmailMessage

import mysql.connector
from flask import Flask, render_template, request, redirect, session, url_for

app = Flask(__name__, template_folder="Templates", static_folder="Static")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

DATABASE_NAME = os.getenv("MYSQL_DATABASE", "tailor_shop")

if not DATABASE_NAME.replace("_", "").isalnum():
    raise ValueError("MYSQL_DATABASE can only contain letters, numbers, and underscores.")

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "user": os.getenv("MYSQL_USER", "tailor_app"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": DATABASE_NAME,
}

ORDER_STATUSES = ["Pending", "In Progress", "Ready for Trial", "Completed"]
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

SMTP_CONFIG = {
    "host": os.getenv("SMTP_HOST", ""),
    "port": int(os.getenv("SMTP_PORT", "587")),
    "user": os.getenv("SMTP_USER", ""),
    "password": os.getenv("SMTP_PASSWORD", ""),
    "from_email": os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_USER", "")),
}


def get_db_connection(use_database=True):
    config = DB_CONFIG.copy()
    if not use_database:
        config.pop("database")
    return mysql.connector.connect(**config)


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            phone VARCHAR(20),
            email VARCHAR(150),
            neck DECIMAL(5, 2) NOT NULL,
            waist DECIMAL(5, 2) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_order_contact_columns(cursor)

    cursor.execute("SELECT COUNT(*) AS total FROM orders")
    if cursor.fetchone()["total"] == 0:
        cursor.executemany(
            """
            INSERT INTO orders (name, phone, email, neck, waist, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                ("Alex Rivera", "9876543210", "alex@example.com", 15.5, 32, "In Progress"),
                ("Sam Chen", "9876543211", "sam@example.com", 16, 34, "Pending"),
            ],
        )

    conn.commit()
    conn.close()

def ensure_order_contact_columns(cursor):
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'orders'
        """,
        (DATABASE_NAME,),
    )
    existing_columns = {row["COLUMN_NAME"] for row in cursor.fetchall()}

    if "phone" not in existing_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN phone VARCHAR(20) AFTER name")

    if "email" not in existing_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN email VARCHAR(150) AFTER phone")

def send_status_email(order):
    if not order.get("email") or not SMTP_CONFIG["host"] or not SMTP_CONFIG["from_email"]:
        return "skipped"

    message = EmailMessage()
    message["Subject"] = f"TailorTrack order #{order['id']} status update"
    message["From"] = SMTP_CONFIG["from_email"]
    message["To"] = order["email"]
    message.set_content(
        f"""Hello {order['name']},

Your boutique order #{order['id']} status is now: {order['status']}.

You can track it anytime using your order number.

Thank you,
TailorTrack
"""
    )

    try:
        with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"], timeout=10) as server:
            server.starttls()
            if SMTP_CONFIG["user"] and SMTP_CONFIG["password"]:
                server.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
            server.send_message(message)
    except (OSError, smtplib.SMTPException):
        return "failed"

    return "sent"

def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view

@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM orders ORDER BY id DESC")
    orders = cursor.fetchall()
    conn.close()
    return render_template('index.html', orders=orders)

@app.route('/add', methods=['GET', 'POST'])
@admin_required
def add_order():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO orders (name, phone, email, neck, waist, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                request.form['name'].strip(),
                request.form['phone'].strip(),
                request.form['email'].strip(),
                float(request.form['neck']),
                float(request.form['waist']),
                "Pending",
            ),
        )
        conn.commit()
        order_id = cursor.lastrowid
        conn.close()
        return redirect(url_for('track_order', order_id=order_id, created='1'))
    return render_template('add_order.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    next_url = request.args.get("next") or url_for("admin_orders")

    if request.method == 'POST':
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        next_url = request.form.get("next") or url_for("admin_orders")

        if username == ADMIN_USERNAME and ADMIN_PASSWORD and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(next_url)

        error = "Invalid admin username or password."

    return render_template('admin_login.html', error=error, next_url=next_url)

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/track', methods=['GET', 'POST'])
def track_order():
    order = None
    searched = False
    created = request.args.get('created') == '1'
    order_id = request.args.get('order_id', '').strip()

    if request.method == 'POST':
        order_id = request.form.get('order_id', '').strip()
        return redirect(url_for('track_order', order_id=order_id))

    if order_id:
        searched = True
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()
        conn.close()

    return render_template(
        'track_order.html',
        order=order,
        order_id=order_id,
        searched=searched,
        created=created,
    )

@app.route('/admin/orders')
@admin_required
def admin_orders():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM orders ORDER BY id DESC")
    orders = cursor.fetchall()
    conn.close()
    return render_template(
        'admin_orders.html',
        orders=orders,
        statuses=ORDER_STATUSES,
        updated=request.args.get('updated'),
        email_status=request.args.get('email_status'),
    )

@app.route('/admin/orders/<int:order_id>/status', methods=['POST'])
@admin_required
def update_order_status(order_id):
    status = request.form.get('status', '').strip()
    if status not in ORDER_STATUSES:
        return redirect(url_for('admin_orders'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
    conn.commit()
    cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    order = cursor.fetchone()
    conn.close()
    email_status = send_status_email(order) if order else "skipped"
    return redirect(url_for('admin_orders', updated=order_id, email_status=email_status))

@app.route('/admin/orders/<int:order_id>/edit')
@admin_required
def edit_order(order_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    order = cursor.fetchone()
    conn.close()

    if not order:
        return redirect(url_for('admin_orders'))

    return render_template('edit_order.html', order=order, statuses=ORDER_STATUSES)

@app.route('/admin/orders/<int:order_id>/edit', methods=['POST'])
@admin_required
def update_order_details(order_id):
    status = request.form.get('status', '').strip()
    if status not in ORDER_STATUSES:
        return redirect(url_for('edit_order', order_id=order_id))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT status FROM orders WHERE id = %s", (order_id,))
    existing_order = cursor.fetchone()

    if not existing_order:
        conn.close()
        return redirect(url_for('admin_orders'))

    cursor.execute(
        """
        UPDATE orders
        SET name = %s,
            phone = %s,
            email = %s,
            neck = %s,
            waist = %s,
            status = %s
        WHERE id = %s
        """,
        (
            request.form['name'].strip(),
            request.form['phone'].strip(),
            request.form['email'].strip(),
            float(request.form['neck']),
            float(request.form['waist']),
            status,
            order_id,
        ),
    )
    conn.commit()
    cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    order = cursor.fetchone()
    conn.close()

    email_status = "skipped"
    if order and existing_order["status"] != status:
        email_status = send_status_email(order)

    return redirect(url_for('admin_orders', updated=order_id, email_status=email_status))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

init_db()

if __name__ == '__main__':
    app.run(debug=True)
