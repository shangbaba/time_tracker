# Time Tracker Flask App

A personal time tracking web application built with Flask, designed for users 60+ with large buttons and simple interface.

## Features
- ⏰ Time entry with smart defaults (9 AM - 5 PM)
- 📊 History view with paid/unpaid tracking
- 💰 Bulk "Pay All" functionality
- 📄 PDF export for unpaid entries
- ⚙️ Settings for hourly rate (AUD)
- 📱 Mobile-friendly responsive design
- 🌙 Overnight shift support
- 📲 PWA ready for iPhone installation

## Setup
1. Clone repository
2. Install dependencies: `pip install -r requirements.txt`
3. Run app: `python app.py`
4. Visit: http://localhost:5000

## Tech Stack
- Flask + SQLAlchemy
- Bootstrap 5
- SQLite database
- ReportLab for PDF generation
