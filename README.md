# Smart Inventory Platform

A Flask-based inventory management application for tracking stock, low-stock alerts, reports, forecasting, and team access roles.

## Features
- Inventory dashboard and search
- Product add/edit/delete flow
- Inventory reports and forecasting
- Low stock notifications
- User authentication with roles: admin, manager, staff
- Deployment-ready SMTP/email configuration support
- Modern glassmorphism UI

## Default login
- Username: admin
- Password: admin123

## Local run
```bash
python app.py
```

## Production deployment
```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

## Email configuration
Copy `.env.example` to `.env` and set your SMTP values before sending real emails.

## Files
- `app.py` : main application
- `templates/` : HTML templates
- `static/css/style.css` : styling
- `requirements.txt` : dependencies
"# inventory-system" 
