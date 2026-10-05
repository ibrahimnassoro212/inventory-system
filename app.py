from flask import Flask, render_template, request, redirect, url_for, Response, session, flash
from functools import wraps
import csv
import os
import smtplib
import sqlite3
from email.message import EmailMessage
from io import StringIO
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "smart_inventory_secret_key_123")
app.config.update(
    DEFAULT_ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", "admin@smartinventory.local"),
    DEFAULT_FROM_EMAIL=os.environ.get("MAIL_DEFAULT_SENDER", "noreply@smartinventory.local"),
    SMTP_SERVER=os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
    SMTP_PORT=int(os.environ.get("SMTP_PORT", "587")),
    SMTP_USERNAME=os.environ.get("SMTP_USERNAME", ""),
    SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
    SMTP_USE_TLS=os.environ.get("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes"),
)

DATABASE = os.environ.get("DATABASE_PATH", "inventory.db")

translations = {
    "en": {
        "dashboard": "Dashboard",
        "products": "Products",
        "reports": "Reports",
        "forecast": "Forecast",
        "settings": "Settings",
        "add_product": "Add Product",
        "login": "Login",
        "logout": "Logout",
        "register": "Register",
    },
    "sw": {
        "dashboard": "Dashibodi",
        "products": "Bidhaa",
        "reports": "Ripoti",
        "forecast": "Utabiri",
        "settings": "Mipangilio",
        "add_product": "Ongeza Bidhaa",
        "login": "Ingia",
        "logout": "Toka",
        "register": "Jisajili",
    },
}


@app.context_processor
def inject_lang():
    lang = session.get("lang", "en")
    return {
        "lang": lang,
        "t": translations.get(lang, translations["en"]),
        "current_user": get_current_user(),
    }


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not get_current_user():
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapper


def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return redirect(url_for("login", next=request.path))
            if user.get("role") not in allowed_roles:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("dashboard"))
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def get_app_setting(key, default=""):
    conn = get_db()
    value = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return value[0] if value else default


def save_app_setting(key, value):
    conn = get_db()
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def send_email(subject, body, recipients=None):
    recipients = recipients or [app.config.get("DEFAULT_ADMIN_EMAIL")]
    smtp_server = app.config.get("SMTP_SERVER")
    smtp_user = app.config.get("SMTP_USERNAME")
    smtp_password = app.config.get("SMTP_PASSWORD")

    if not smtp_server or not smtp_user or not smtp_password:
        return {
            "status": "queued",
            "message": "SMTP is not configured. Email is ready to send once deployment credentials are added.",
        }

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = app.config.get("DEFAULT_FROM_EMAIL")
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    try:
        with smtplib.SMTP(smtp_server, app.config.get("SMTP_PORT", 587)) as server:
            if app.config.get("SMTP_USE_TLS"):
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_password)
            server.send_message(message)
        return {"status": "sent", "message": "Email sent successfully"}
    except Exception as exc:  # pragma: no cover - deployment hook
        return {"status": "failed", "message": str(exc)}


@app.route("/change-language/<lang_code>")
def change_language(lang_code):
    if lang_code in ["en", "sw"]:
        session["lang"] = lang_code
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_current_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (username, username),
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            next_page = request.args.get("next") or url_for("dashboard")
            return redirect(next_page)

        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if get_current_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "staff")

        if not username or not email or not password:
            flash("Please fill in all fields.", "warning")
            return render_template("register.html")

        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?",
            (username, email),
        ).fetchone()
        if existing:
            conn.close()
            flash("This username or email already exists.", "danger")
            return render_template("register.html")

        conn.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, email, generate_password_hash(password), role if role in ("admin", "manager", "staff") else "staff"),
        )
        conn.commit()
        conn.close()
        flash("Account created successfully. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/users")
@login_required
@role_required("admin")
def users():
    conn = get_db()
    user_list = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
    conn.close()
    return render_template("users.html", users=user_list)


@app.route("/users/<int:user_id>/role/<role>", methods=["POST"])
@login_required
@role_required("admin")
def update_user_role(user_id, role):
    if role in {"admin", "manager", "staff"}:
        conn = get_db()
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        conn.commit()
        conn.close()
        flash("User role updated successfully.", "success")
    else:
        flash("Invalid role selected.", "danger")
    return redirect(url_for("users"))


@app.route("/send-email-alert", methods=["POST"])
@login_required
def send_email_alert():
    product_id = request.form.get("product_id")
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone() if product_id else None
    conn.close()

    if product:
        recipients = [app.config.get("DEFAULT_ADMIN_EMAIL")]
        results = send_email(
            f"Low Stock Alert: {product['name']}",
            f"The item {product['name']} is running low. Remaining quantity: {product['quantity']}.",
            recipients,
        )
        flash(results["message"], "success" if results["status"] == "sent" else "warning")
    else:
        flash("No product selected for email alert.", "warning")
    return redirect(url_for("dashboard"))


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            product_name TEXT NOT NULL,
            details TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    admin_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if admin_count == 0:
        conn.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ("admin", "admin@smartinventory.local", generate_password_hash("admin123"), "admin"),
        )

    for key, value in {
        "smtp_server": app.config.get("SMTP_SERVER", "smtp.gmail.com"),
        "smtp_port": str(app.config.get("SMTP_PORT", 587)),
        "smtp_username": app.config.get("SMTP_USERNAME", ""),
        "smtp_password": app.config.get("SMTP_PASSWORD", ""),
        "mail_default_sender": app.config.get("DEFAULT_FROM_EMAIL", "noreply@smartinventory.local"),
        "admin_email": app.config.get("DEFAULT_ADMIN_EMAIL", "admin@smartinventory.local"),
    }.items():
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    conn.commit()
    conn.close()


@app.route("/")
def dashboard():
    search = request.args.get("search", "").strip()
    conn = get_db()

    if search:
        products = conn.execute(
            """
            SELECT * FROM products
            WHERE name LIKE ? OR category LIKE ?
            ORDER BY id DESC
            """,
            (f"%{search}%", f"%{search}%"),
        ).fetchall()
    else:
        products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()

    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_stock = conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM products").fetchone()[0]
    low_stock = conn.execute("SELECT COUNT(*) FROM products WHERE quantity <= 5").fetchone()[0]
    inventory_value = conn.execute("SELECT COALESCE(SUM(quantity * price), 0) FROM products").fetchone()[0]
    conn.close()

    return render_template(
        "dashboard.html",
        products=products,
        total_products=total_products,
        total_stock=total_stock,
        low_stock=low_stock,
        inventory_value=inventory_value,
        search=search,
    )


@app.route("/products")
def products():
    search = request.args.get("search", "").strip()
    conn = get_db()
    if search:
        products = conn.execute(
            "SELECT * FROM products WHERE name LIKE ? OR category LIKE ? ORDER BY id DESC",
            (f"%{search}%", f"%{search}%"),
        ).fetchall()
    else:
        products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("products.html", products=products, search=search)


@app.route("/reports")
def reports():
    conn = get_db()
    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_stock = conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM products").fetchone()[0]
    inventory_value = conn.execute("SELECT COALESCE(SUM(quantity * price), 0) FROM products").fetchone()[0]
    low_stock = conn.execute("SELECT COUNT(*) FROM products WHERE quantity > 0 AND quantity <= 5").fetchone()[0]
    out_of_stock = conn.execute("SELECT COUNT(*) FROM products WHERE quantity = 0").fetchone()[0]
    categories = conn.execute(
        "SELECT category, COUNT(*) AS product_count, COALESCE(SUM(quantity), 0) AS stock, COALESCE(SUM(quantity * price), 0) AS value FROM products GROUP BY category ORDER BY value DESC"
    ).fetchall()
    recent_activity = conn.execute("SELECT * FROM history ORDER BY timestamp DESC LIMIT 10").fetchall()
    conn.close()
    return render_template(
        "reports.html",
        total_products=total_products,
        total_stock=total_stock,
        inventory_value=inventory_value,
        low_stock=low_stock,
        out_of_stock=out_of_stock,
        categories=categories,
        recent_activity=recent_activity,
    )


@app.route("/add-product", methods=["GET", "POST"])
def add_product():
    if request.method == "POST":
        if not get_current_user():
            return redirect(url_for("login", next=request.path))
        name = request.form["name"]
        category = request.form["category"]
        quantity = request.form["quantity"]
        price = request.form["price"]

        conn = get_db()
        conn.execute(
            "INSERT INTO products (name, category, quantity, price) VALUES (?, ?, ?, ?)",
            (name, category, quantity, price),
        )
        conn.execute(
            "INSERT INTO history (action, product_name, details) VALUES (?, ?, ?)",
            ("CREATED", name, f"Added {quantity} units at ${price} each."),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("dashboard"))
    return render_template("add_product.html")


@app.route("/delete-product/<int:id>", methods=["POST"])
def delete_product(id):
    if not get_current_user():
        return redirect(url_for("login", next=request.path))
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (id,)).fetchone()
    if product:
        conn.execute("DELETE FROM products WHERE id = ?", (id,))
        conn.execute(
            "INSERT INTO history (action, product_name, details) VALUES (?, ?, ?)",
            ("DELETED", product["name"], "Product removed from inventory."),
        )
        conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))


@app.route("/edit-product/<int:id>", methods=["GET", "POST"])
def edit_product(id):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (id,)).fetchone()
    if product is None:
        conn.close()
        return "Product not found", 404

    if request.method == "POST":
        if not get_current_user():
            conn.close()
            return redirect(url_for("login", next=request.path))
        name = request.form["name"]
        category = request.form["category"]
        quantity = request.form["quantity"]
        price = request.form["price"]
        conn.execute(
            "UPDATE products SET name = ?, category = ?, quantity = ?, price = ? WHERE id = ?",
            (name, category, quantity, price, id),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("dashboard"))
    conn.close()
    return render_template("edit_product.html", product=product)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    email_settings = {
        "smtp_server": get_app_setting("smtp_server", app.config.get("SMTP_SERVER", "smtp.gmail.com")),
        "smtp_port": get_app_setting("smtp_port", str(app.config.get("SMTP_PORT", 587))),
        "smtp_username": get_app_setting("smtp_username", app.config.get("SMTP_USERNAME", "")),
        "smtp_password": get_app_setting("smtp_password", app.config.get("SMTP_PASSWORD", "")),
        "mail_default_sender": get_app_setting("mail_default_sender", app.config.get("DEFAULT_FROM_EMAIL", "noreply@smartinventory.local")),
        "admin_email": get_app_setting("admin_email", app.config.get("DEFAULT_ADMIN_EMAIL", "admin@smartinventory.local")),
    }

    if request.method == "POST":
        if not get_current_user():
            return redirect(url_for("login", next=request.path))
        app.config["SMTP_SERVER"] = request.form.get("smtp_server") or app.config["SMTP_SERVER"]
        app.config["SMTP_PORT"] = int(request.form.get("smtp_port") or app.config["SMTP_PORT"])
        app.config["SMTP_USERNAME"] = request.form.get("smtp_username") or app.config["SMTP_USERNAME"]
        app.config["SMTP_PASSWORD"] = request.form.get("smtp_password") or app.config["SMTP_PASSWORD"]
        app.config["DEFAULT_FROM_EMAIL"] = request.form.get("mail_default_sender") or app.config["DEFAULT_FROM_EMAIL"]
        app.config["DEFAULT_ADMIN_EMAIL"] = request.form.get("admin_email") or app.config["DEFAULT_ADMIN_EMAIL"]

        for key, value in {
            "smtp_server": app.config["SMTP_SERVER"],
            "smtp_port": str(app.config["SMTP_PORT"]),
            "smtp_username": app.config["SMTP_USERNAME"],
            "smtp_password": app.config["SMTP_PASSWORD"],
            "mail_default_sender": app.config["DEFAULT_FROM_EMAIL"],
            "admin_email": app.config["DEFAULT_ADMIN_EMAIL"],
        }.items():
            save_app_setting(key, value)

        flash("Email configuration updated successfully.", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html", email_settings=email_settings)


@app.route("/forecast")
def forecast():
    conn = get_db()
    products = conn.execute("SELECT * FROM products").fetchall()
    forecast_data = []
    for p in products:
        qty = p["quantity"]
        burn_rate = max(0.5, round(qty * 0.05, 1))
        runway_days = round(qty / burn_rate, 1) if burn_rate > 0 else 999
        eoq = max(10, round(burn_rate * 14))
        forecast_data.append(
            {
                "id": p["id"],
                "name": p["name"],
                "category": p["category"],
                "quantity": qty,
                "burn_rate": burn_rate,
                "runway_days": runway_days,
                "eoq": eoq,
            }
        )
    conn.close()
    return render_template("forecast.html", forecast=forecast_data)


@app.route("/api/notifications")
def get_notifications():
    conn = get_db()
    low_items = conn.execute("SELECT id, name, quantity FROM products WHERE quantity <= 5").fetchall()
    conn.close()
    notifications = [
        {
            "id": item["id"],
            "title": f"Low Stock: {item['name']}",
            "message": f"Only {item['quantity']} units remaining.",
            "read": False,
        }
        for item in low_items
    ]
    return {"notifications": notifications, "count": len(notifications)}


@app.route("/adjust-stock/<int:id>/<action>", methods=["POST"])
def adjust_stock(id, action):
    if not get_current_user():
        return redirect(url_for("login", next=request.path))
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (id,)).fetchone()
    if product:
        current_qty = product["quantity"]
        new_qty = current_qty + 1 if action == "increase" else max(0, current_qty - 1)
        db.execute("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, id))
        db.commit()
    db.close()
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/export-csv")
def export_csv():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY id ASC").fetchall()
    conn.close()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["ID", "Name", "Category", "Quantity", "Price"])
    for product in products:
        cw.writerow([product["id"], product["name"], product["category"], product["quantity"], product["price"]])
    output = si.getvalue()
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=inventory_report.csv"})


def seed_realistic_data():
    conn = get_db()
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        sample_items = [
            ("MacBook Pro M3", "Electronics", 4, 1999.99),
            ("Ergonomic Office Chair", "Furniture", 12, 249.50),
            ("USB-C Hub Multiport", "Accessories", 2, 45.00),
            ("Mechanical Keyboards", "Electronics", 15, 89.99),
        ]
        conn.executemany(
            "INSERT INTO products (name, category, quantity, price) VALUES (?, ?, ?, ?)",
            sample_items,
        )
        conn.commit()
    conn.close()


init_db()
seed_realistic_data()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False, use_reloader=False)