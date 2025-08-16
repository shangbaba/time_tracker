# app.py - Main Flask Application
from flask import send_from_directory
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, DateField, TimeField, SelectField, SubmitField
from wtforms.validators import DataRequired, NumberRange
from datetime import datetime, date, time, timedelta
from dateutil import parser
import os
import json
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///timetracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Models
class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    current_rate = db.Column(db.Numeric(10, 2), nullable=False, default=25.00)
    currency_symbol = db.Column(db.String(5), nullable=False, default='$')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @classmethod
    def get_current_rate(cls):
        settings = cls.query.first()
        if not settings:
            settings = cls(current_rate=25.00, currency_symbol='$')
            db.session.add(settings)
            db.session.commit()
        return float(settings.current_rate)

class TimeEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sequence_number = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    rate_at_entry = db.Column(db.Numeric(10, 2), nullable=False)
    total_hours = db.Column(db.Numeric(5, 2), nullable=False)
    total_pay = db.Column(db.Numeric(10, 2), nullable=False)
    is_paid = db.Column(db.Boolean, default=False)
    is_overnight = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @classmethod
    def get_next_sequence(cls):
        last_entry = cls.query.order_by(cls.sequence_number.desc()).first()
        return (last_entry.sequence_number + 1) if last_entry else 1
    
    def calculate_hours(self):
        """Calculate total hours including overnight shifts"""
        start_datetime = datetime.combine(self.date, self.start_time)
        
        if self.is_overnight:
            # End time is next day
            end_datetime = datetime.combine(self.date + timedelta(days=1), self.end_time)
        else:
            end_datetime = datetime.combine(self.date, self.end_time)
        
        duration = end_datetime - start_datetime
        return round(duration.total_seconds() / 3600, 2)
    
    def format_currency(self, amount):
        """Format amount as AUD currency"""
        return f"${amount:,.2f}"

# Forms
class SettingsForm(FlaskForm):
    current_rate = DecimalField('Current Hourly Rate (AUD)', validators=[
        DataRequired(), NumberRange(min=0.01, max=999.99)
    ], places=2)
    submit = SubmitField('Save Settings')

class TimeEntryForm(FlaskForm):
    date = DateField('Date', validators=[DataRequired()], default=date.today)
    start_time = TimeField('Start Time', validators=[DataRequired()], default=time(9, 0))  # 9:00 AM
    end_time = TimeField('End Time', validators=[DataRequired()], default=time(17, 0))    # 5:00 PM
    submit = SubmitField('Save Entry')

class DateRangeForm(FlaskForm):
    start_date = DateField('From Date', validators=[DataRequired()])
    end_date = DateField('To Date', validators=[DataRequired()])
    submit = SubmitField('Filter')

# Utility functions
def format_currency(amount):
    """Format amount as AUD currency"""
    return f"${float(amount):,.2f}"

def is_overnight_shift(start_time, end_time):
    """Auto-detect if shift spans midnight"""
    return end_time <= start_time

# Routes
@app.route('/')
def index():
    return redirect(url_for('time_entry'))

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    form = SettingsForm()
    settings = Settings.query.first()
    
    if not settings:
        settings = Settings()
        db.session.add(settings)
        db.session.commit()
    
    if form.validate_on_submit():
        settings.current_rate = form.current_rate.data
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    
    form.current_rate.data = settings.current_rate
    return render_template('settings.html', form=form, settings=settings)

# # Minimal test for /entry route
# @app.route('/entry', methods=['GET', 'POST'])
# def time_entry():
#     return "<h1>This is the time entry page</h1>"


@app.route('/entry', methods=['GET', 'POST'])
def time_entry():
    form = TimeEntryForm()
    
    if form.validate_on_submit():
        # Auto-detect overnight shift
        overnight = is_overnight_shift(form.start_time.data, form.end_time.data)
        
        # Validation: prevent impossible times (unless overnight)
        if not overnight and form.end_time.data <= form.start_time.data:
            flash('End time must be after start time for same-day shifts.', 'error')
            return render_template('time_entry.html', form=form)
        
        # Create new entry
        current_rate = Settings.get_current_rate()
        entry = TimeEntry(
            sequence_number=TimeEntry.get_next_sequence(),
            date=form.date.data,
            start_time=form.start_time.data,
            end_time=form.end_time.data,
            rate_at_entry=current_rate,
            is_overnight=overnight
        )
        
        # Calculate hours and pay
        entry.total_hours = entry.calculate_hours()
        entry.total_pay = float(entry.total_hours) * current_rate
        
        # Validation warnings
        if entry.total_hours == 0:
            flash('Warning: Shift duration is 0 hours.', 'warning')
        elif entry.total_hours > 16:
            flash('Warning: Shift duration exceeds 16 hours.', 'warning')
        
        db.session.add(entry)
        db.session.commit()
        
        flash(f'Time entry #{entry.sequence_number} saved! Total: {entry.total_hours}h, Pay: {format_currency(entry.total_pay)}', 'success')
        return redirect(url_for('time_entry'))
    
    return render_template('time_entry.html', form=form)

@app.route('/history')
def history():
    show_paid = request.args.get('show_paid', 'true') == 'true'
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = TimeEntry.query
    
    # Filter by paid status
    if not show_paid:
        query = query.filter_by(is_paid=False)
    
    # Date range filtering
    if start_date:
        query = query.filter(TimeEntry.date >= parser.parse(start_date).date())
    if end_date:
        query = query.filter(TimeEntry.date <= parser.parse(end_date).date())
    
    entries = query.order_by(TimeEntry.date.asc(), TimeEntry.start_time.asc()).all()
    
    # Calculate statistics
    stats = {
        'total_hours': sum(float(e.total_hours) for e in entries),
        'total_pay': sum(float(e.total_pay) for e in entries),
        'unpaid_hours': sum(float(e.total_hours) for e in entries if not e.is_paid),
        'unpaid_pay': sum(float(e.total_pay) for e in entries if not e.is_paid),
    }
    
    return render_template('history.html', 
                         entries=entries, 
                         stats=stats, 
                         show_paid=show_paid,
                         format_currency=format_currency)

@app.route('/toggle_paid/<int:entry_id>')
def toggle_paid(entry_id):
    entry = TimeEntry.query.get_or_404(entry_id)
    entry.is_paid = not entry.is_paid
    db.session.commit()
    
    status = "paid" if entry.is_paid else "unpaid"
    flash(f'Entry #{entry.sequence_number} marked as {status}.', 'success')
    return redirect(url_for('history'))

@app.route('/delete_entry/<int:entry_id>')
def delete_entry(entry_id):
    entry = TimeEntry.query.get_or_404(entry_id)
    seq_num = entry.sequence_number
    db.session.delete(entry)
    db.session.commit()
    
    flash(f'Entry #{seq_num} deleted successfully.', 'success')
    return redirect(url_for('history'))

@app.route('/pay_all')
def pay_all():
    """Mark all filtered entries as paid"""
    show_paid = request.args.get('show_paid', 'true') == 'true'
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = TimeEntry.query
    
    # Apply same filters as history view
    if start_date:
        query = query.filter(TimeEntry.date >= parser.parse(start_date).date())
    if end_date:
        query = query.filter(TimeEntry.date <= parser.parse(end_date).date())
    
    # Only get unpaid entries (we're marking them as paid)
    unpaid_entries = query.filter_by(is_paid=False).all()
    
    if not unpaid_entries:
        flash('No unpaid entries found to mark as paid.', 'warning')
    else:
        # Mark all filtered unpaid entries as paid
        count = 0
        total_amount = 0
        for entry in unpaid_entries:
            entry.is_paid = True
            count += 1
            total_amount += float(entry.total_pay)
        
        db.session.commit()
        
        flash(f'Marked {count} entries as paid. Total: {format_currency(total_amount)}', 'success')
    
    # Redirect back to history with same filters
    return redirect(url_for('history', 
                          show_paid=show_paid, 
                          start_date=start_date, 
                          end_date=end_date))

@app.route('/export_pdf')
def export_pdf():
    # Get unpaid entries only
    entries = TimeEntry.query.filter_by(is_paid=False).order_by(
        TimeEntry.date.asc(), TimeEntry.start_time.asc()
    ).all()
    
    if not entries:
        flash('No unpaid entries to export.', 'warning')
        return redirect(url_for('history'))
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=1  # Center alignment
    )
    elements.append(Paragraph("Unpaid Time Entries Report", title_style))
    elements.append(Spacer(1, 20))
    
    # Table data
    data = [['#', 'Date', 'Start', 'End', 'Hours', 'Rate', 'Pay']]
    
    total_hours = 0
    total_pay = 0
    
    for entry in entries:
        data.append([
            str(entry.sequence_number),
            entry.date.strftime('%d/%m/%Y'),
            entry.start_time.strftime('%H:%M'),
            entry.end_time.strftime('%H:%M'),
            f"{float(entry.total_hours):.2f}",
            f"${float(entry.rate_at_entry):.2f}",
            f"${float(entry.total_pay):.2f}"
        ])
        total_hours += float(entry.total_hours)
        total_pay += float(entry.total_pay)
    
    # Add totals row
    data.append(['', '', '', 'TOTAL:', f"{total_hours:.2f}", '', f"${total_pay:.2f}"])
    
    # Create table
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, -1), (-1, -1), colors.beige),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'unpaid_entries_{datetime.now().strftime("%Y%m%d")}.pdf',
        mimetype='application/pdf'
    )

@app.route('/backup')
def backup_data():
    """Export all data as JSON"""
    data = {
        'settings': [{
            'current_rate': float(s.current_rate),
            'currency_symbol': s.currency_symbol,
            'created_at': s.created_at.isoformat()
        } for s in Settings.query.all()],
        'entries': [{
            'sequence_number': e.sequence_number,
            'date': e.date.isoformat(),
            'start_time': e.start_time.strftime('%H:%M:%S'),
            'end_time': e.end_time.strftime('%H:%M:%S'),
            'rate_at_entry': float(e.rate_at_entry),
            'total_hours': float(e.total_hours),
            'total_pay': float(e.total_pay),
            'is_paid': e.is_paid,
            'is_overnight': e.is_overnight,
            'created_at': e.created_at.isoformat()
        } for e in TimeEntry.query.all()]
    }
    
    return jsonify(data)

# @app.route('/static/manifest.json')
# def manifest():
#     return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

# @app.route('/static/sw.js')
# def service_worker():
#     return send_from_directory('static', 'sw.js', mimetype='application/javascript')

# Additional app.py routes for PWA support
# Add these routes to your app.py file:

@app.route('/static/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@app.route('/static/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)