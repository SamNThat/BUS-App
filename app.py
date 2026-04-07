import datetime
import threading
import time
from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from models import Medication, Patient, Carer

app = Flask(__name__)
app.secret_key = 'medication-tracker-secret'

# Create the data objects
carer = Carer('Sarah')
patient = Patient('Doris', 71)
medication = Medication('Aricept', 3, 2, 4, 9)
patient.add_medication(medication)
carer.add_patient(patient)

# Simple login credentials
USERS = {
    'doris': {'password': '1234', 'role': 'patient'},
    'sarah': {'password': '5678', 'role': 'carer'}
}


# Background monitoring thread
def check_for_missed_doses():
    """Check every minute if doses have been missed"""
    checked_doses = set()
    
    while True:
        now = datetime.datetime.now()
        
        for med in patient.medications:
            for dose_time in med.dose_times:
                window_end = dose_time + datetime.timedelta(hours=med.window_hours)
                dose_key = f"{med.name}_{dose_time}"
                
                # If window has closed and we haven't checked this dose yet
                if now > window_end and dose_key not in checked_doses:
                    # Check if patient took this dose
                    dose_was_taken = any(
                        d['medication_name'] == med.name and
                        dose_time <= d['time'] <= window_end
                        for d in patient.doses_taken
                    )
                    
                    # If not taken, record as missed
                    if not dose_was_taken:
                        patient.record_missed(med, dose_time)
                        alert_message = f"{patient.name} missed {med.name} at {dose_time.strftime('%H:%M')}"
                        carer.add_alert(alert_message)
                        print(f"Alert: {alert_message}")
                    
                    checked_doses.add(dose_key)
        
        time.sleep(60)  # Check every minute


# Start the background thread
monitor = threading.Thread(target=check_for_missed_doses, daemon=True)
monitor.start()


# Routes
@app.route('/')
def home():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username in USERS and USERS[username]['password'] == password:
            session['username'] = username
            session['role'] = USERS[username]['role']
            
            if session['role'] == 'patient':
                return redirect(url_for('patient_view'))
            else:
                return redirect(url_for('carer_view'))
        else:
            error = 'Invalid username or password'
    
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/patient')
def patient_view():
    if session.get('role') != 'patient':
        return redirect(url_for('login'))
    
    # Get medication schedule
    schedule = []
    now = datetime.datetime.now()
    
    for med in patient.medications:
        doses = []
        for dose_time in med.dose_times:
            window_end = dose_time + datetime.timedelta(hours=med.window_hours)
            
            if dose_time <= now <= window_end:
                status = 'due'
            elif now > window_end:
                status = 'missed'
            else:
                status = 'upcoming'
            
            doses.append({
                'time': dose_time.strftime('%H:%M'),
                'status': status
            })
        
        # Check if medication is currently due AND hasn't been taken yet
        is_due = False
        if med.is_dose_due_now():
            # Find which dose window we're in
            for dose_time in med.dose_times:
                window_end = dose_time + datetime.timedelta(hours=med.window_hours)
                if dose_time <= now <= window_end:
                    # Check if this specific dose has already been taken
                    already_taken = any(
                        d['medication_name'] == med.name and
                        dose_time <= d['time'] <= window_end
                        for d in patient.doses_taken
                    )
                    if not already_taken:
                        is_due = True
                    break
        
        schedule.append({
            'name': med.name,
            'doses': doses,
            'is_due': is_due
        })
    
    recent_doses = patient.get_recent_doses()
    
    return render_template('patient.html',
                         patient=patient,
                         schedule=schedule,
                         recent_doses=recent_doses)


@app.route('/patient/take/<medication_name>', methods=['POST'])
def take_medication(medication_name):
    if session.get('role') != 'patient':
        return jsonify({'success': False}), 403
    
    for med in patient.medications:
        if med.name == medication_name:
            if med.is_dose_due_now():
                patient.take_dose(med)
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'message': 'Not due yet'})
    
    return jsonify({'success': False}), 404


@app.route('/carer')
def carer_view():
    if session.get('role') != 'carer':
        return redirect(url_for('login'))
    
    # Calculate statistics
    total_taken = len(patient.doses_taken)
    total_missed = len(patient.doses_missed)
    
    return render_template('carer.html',
                         carer=carer,
                         patient=patient,
                         total_taken=total_taken,
                         total_missed=total_missed,
                         alerts=carer.alerts[-10:])  # Show last 10 alerts


if __name__ == '__main__':
    app.run(debug=True, port=5000)
