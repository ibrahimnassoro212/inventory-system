from flask import Flask, render_template, request, redirect, url_for, Response, session
import sqlite3
import csv
from io import StringIO

app = Flask(__name__)
app.secret_key = 'smart_inventory_secret_key_123' # Funguo ya session

DATABASE = "inventory.db"

# --- 1. Mfumo wa Lugha (Translations) ---
translations = {
    'en': {
        'dashboard': 'Dashboard',
        'products': 'Products',
        'reports': 'Reports',
        'forecast': 'Forecast',
        'settings': 'Settings',
        'add_product': 'Add Product'
    },
    'sw': {
        'dashboard': 'Dashibodi',
        'products': 'Bidhaa',
        'reports': 'Ripoti',
        'forecast': 'Utabiri',
        'settings': 'Mipangilio',
        'add_product': 'Ongeza Bidhaa'
    }
}

@app.context_processor
def inject_lang():
    lang = session.get('lang', 'en')
    return {'lang': lang, 't': translations[lang]}

@app.route('/change-language/<lang_code>')
def change_language(lang_code):
    if lang_code in ['en', 'sw']:
        session['lang'] = lang_code
    return redirect(request.referrer or url_for('dashboard'))

# --- 2. Database Functions ---
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            product_name TEXT NOT NULL,
            details TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# --- 3. Routes ---
@app.route("/")
def dashboard():
    search = request.args.get("search", "").strip()
    conn = get_db()

    if search:
        products = conn.execute("""
            SELECT * FROM products
            WHERE name LIKE ? OR category LIKE ?
            ORDER BY id DESC
        """, (f"%{search}%", f"%{search}%")).fetchall()
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
        search=search
    )

@app.route("/products")
def products():
    search = request.args.get("search", "").strip()
    conn = get_db()
    if search:
        products = conn.execute("SELECT * FROM products WHERE name LIKE ? OR category LIKE ? ORDER BY id DESC", (f"%{search}%", f"%{search}%")).fetchall()
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
    categories = conn.execute("SELECT category, COUNT(*) AS product_count, COALESCE(SUM(quantity), 0) AS stock, COALESCE(SUM(quantity * price), 0) AS value FROM products GROUP BY category ORDER BY value DESC").fetchall()
    recent_activity = conn.execute("SELECT * FROM history ORDER BY timestamp DESC LIMIT 10").fetchall()
    conn.close()
    return render_template("reports.html", total_products=total_products, total_stock=total_stock, inventory_value=inventory_value, low_stock=low_stock, out_of_stock=out_of_stock, categories=categories, recent_activity=recent_activity)

@app.route("/add-product", methods=["GET", "POST"])
def add_product():
    if request.method == "POST":
        name = request.form["name"]
        category = request.form["category"]
        quantity = request.form["quantity"]
        price = request.form["price"]

        conn = get_db()
        conn.execute("INSERT INTO products (name, category, quantity, price) VALUES (?, ?, ?, ?)", (name, category, quantity, price))
        conn.execute("INSERT INTO history (action, product_name, details) VALUES (?, ?, ?)", ("CREATED", name, f"Added {quantity} units at ${price} each."))
        conn.commit()
        conn.close()
        return redirect(url_for("dashboard"))
    return render_template("add_product.html")

@app.route("/delete-product/<int:id>", methods=["POST"])
def delete_product(id):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (id,)).fetchone()
    if product:
        conn.execute("DELETE FROM products WHERE id = ?", (id,))
        conn.execute("INSERT INTO history (action, product_name, details) VALUES (?, ?, ?)", ("DELETED", product["name"], "Product removed from inventory."))
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
        name = request.form["name"]
        category = request.form["category"]
        quantity = request.form["quantity"]
        price = request.form["price"]
        conn.execute("UPDATE products SET name = ?, category = ?, quantity = ?, price = ? WHERE id = ?", (name, category, quantity, price, id))
        conn.commit()
        conn.close()
        return redirect(url_for("dashboard"))
    conn.close()
    return render_template("edit_product.html", product=product)

@app.route("/settings")
def settings():
    return render_template("settings.html")

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
        forecast_data.append({"id": p["id"], "name": p["name"], "category": p["category"], "quantity": qty, "burn_rate": burn_rate, "runway_days": runway_days, "eoq": eoq})
    conn.close()
    return render_template("forecast.html", forecast=forecast_data)

@app.route("/api/notifications")
def get_notifications():
    conn = get_db()
    low_items = conn.execute("SELECT id, name, quantity FROM products WHERE quantity <= 5").fetchall()
    conn.close()
    notifications = [{"id": item["id"], "title": f"Low Stock: {item['name']}", "message": f"Only {item['quantity']} units remaining.", "read": False} for item in low_items]
    return {"notifications": notifications, "count": len(notifications)}

@app.route('/adjust-stock/<int:id>/<action>', methods=['POST'])
def adjust_stock(id, action):
    db = get_db()
    product = db.execute('SELECT * FROM products WHERE id = ?', (id,)).fetchone()
    if product:
        current_qty = product['quantity']
        new_qty = current_qty + 1 if action == 'increase' else max(0, current_qty - 1)
        db.execute('UPDATE products SET quantity = ? WHERE id = ?', (new_qty, id))
        db.commit()
    db.close()
    return redirect(request.referrer or url_for('dashboard'))

@app.route("/export-csv")
def export_csv():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY id ASC").fetchall()
    conn.close()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Name', 'Category', 'Quantity', 'Price'])
    for product in products:
        cw.writerow([product['id'], product['name'], product['category'], product['quantity'], product['price']])
    output = si.getvalue()
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=inventory_report.csv"})

def seed_realistic_data():
    conn = get_db()
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        sample_items = [
            ("MacBook Pro M3", "Electronics", 4, 1999.99),
            ("Ergonomic Office Chair", "Furniture", 12, 249.50),
            ("USB-C Hub Multiport", "Accessories", 2, 45.00),
            ("Mechanical Keyboards", "Electronics", 15, 89.99)
        ]
        conn.executemany("INSERT INTO products (name, category, quantity, price) VALUES (?, ?, ?, ?)", sample_items)
        conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    seed_realistic_data()
    app.run(debug=True, use_reloader=False)