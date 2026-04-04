import datetime
import threading
import time
from flask import Flask, render_template, redirect, url_for, session, jsonify, request
from models import Medication, Patient, Family, Carer

app = Flask(__name__)
app.secret_key = 'medapp-secret-key-2024'

# ── App state (in-memory, single instance) ──────────────────────────────────
def setup():
    carer = Carer(1, "carer@example.com")
    patient = Patient('Doris', 'Dementia', 1, 71)
    carer.add_patient(patient)

    family = Family('James', 'Son', "james@example.com")
    family.patient = patient
    patient.add_family(family)

    med = Medication('Aricept', 3, 2, 4, 9)
    patient.add_med(med)

    return carer, patient, family

carer, patient, family = setup()

# ── Background monitor ───────────────────────────────────────────────────────
def monitor_medication_windows():
    tracked_windows = {}
    while True:
        now = datetime.datetime.now()
        for med in patient.medication:
            for dose_time in med.medication_timings:
                window_end = dose_time + datetime.timedelta(hours=med.time_window)
                window_key = f"{med.med_name}_{dose_time}"

                if now > window_end and window_key not in tracked_windows:
                    dose_taken = any(
                        d['medication'] == med and
                        dose_time <= d['timestamp'] <= window_end
                        for d in patient.taken_doses
                    )
                    if not dose_taken:
                        patient.record_missed_dose(med, dose_time)
                        msg = f"{patient.name} missed {med.med_name} (due {dose_time.strftime('%H:%M')})"
                        carer.add_notification(msg)
                        print(f"📧 EMAIL to {carer.email}: {msg}")
                    tracked_windows[window_key] = True
        time.sleep(60)

monitor_thread = threading.Thread(target=monitor_medication_windows, daemon=True)
monitor_thread.start()

# ── Helpers ──────────────────────────────────────────────────────────────────
VALID_LOGINS = {
    'patient':  {'pin': '1234', 'role': 'patient'},
    'carer':    {'pin': '5678', 'role': 'carer'},
    'james':    {'pin': '0000', 'role': 'family'},
}

# ── Auth routes ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').lower()
        pin = request.form.get('pin', '')
        if username in VALID_LOGINS and VALID_LOGINS[username]['pin'] == pin:
            session['user'] = username
            session['role'] = VALID_LOGINS[username]['role']
            return redirect(url_for(f"{session['role']}_dashboard"))
        error = 'Invalid username or PIN'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Patient routes ───────────────────────────────────────────────────────────
@app.route('/patient')
def patient_dashboard():
    if session.get('role') != 'patient':
        return redirect(url_for('login'))

    schedule = []
    for med in patient.medication:
        med_schedule = {
            'name': med.med_name,
            'doses': med.get_schedule_status()
        }
        schedule.append(med_schedule)

    today_taken = patient.get_today_taken()
    notifications = patient.get_active_notifications()

    return render_template('patient.html',
                           patient=patient,
                           schedule=schedule,
                           notifications=notifications,
                           today_taken=today_taken,
                           now_hour=datetime.datetime.now().hour)

@app.route('/patient/take/<med_name>', methods=['POST'])
def take_medication(med_name):
    if session.get('role') != 'patient':
        return jsonify({'error': 'Unauthorized'}), 403

    for med in patient.medication:
        if med.med_name == med_name:
            is_open, _ = med.is_window_open()
            if is_open:
                patient.record_medication_taken(med)
                return jsonify({'success': True, 'message': f'{med_name} recorded!'})
            else:
                return jsonify({'success': False, 'message': 'No active window for this medication.'})
    return jsonify({'error': 'Medication not found'}), 404

@app.route('/patient/status')
def patient_status():
    """Polling endpoint — refreshes schedule & notifications."""
    if session.get('role') != 'patient':
        return jsonify({'error': 'Unauthorized'}), 403

    schedule = []
    for med in patient.medication:
        doses = []
        for d in med.get_schedule_status():
            doses.append({
                'dose_number': d['dose_number'],
                'time': d['time'],
                'window_end': d['window_end'],
                'status': d['status']
            })
        schedule.append({'name': med.med_name, 'doses': doses})

    notifications = [{
        'medication': n['medication'],
        'dose_time': n['dose_time'],
        'time_left_minutes': n['time_left_minutes']
    } for n in patient.get_active_notifications()]

    today_taken = [{
        'med_name': d['med_name'],
        'time': d['timestamp'].strftime('%H:%M'),
        'on_time': d['was_on_time']
    } for d in patient.get_today_taken()]

    return jsonify({
        'schedule': schedule,
        'notifications': notifications,
        'today_taken': today_taken
    })

# ── Carer routes ─────────────────────────────────────────────────────────────
@app.route('/carer')
def carer_dashboard():
    if session.get('role') != 'carer':
        return redirect(url_for('login'))
    dashboard = carer.get_dashboard()
    return render_template('carer.html', dashboard=dashboard, carer=carer)

@app.route('/carer/notifications/read', methods=['POST'])
def mark_notifications_read():
    if session.get('role') != 'carer':
        return jsonify({'error': 'Unauthorized'}), 403
    for n in carer.notifications:
        n['read'] = True
    return jsonify({'success': True})

@app.route('/carer/status')
def carer_status():
    if session.get('role') != 'carer':
        return jsonify({'error': 'Unauthorized'}), 403
    dashboard = carer.get_dashboard()
    # Serialise notifications
    notifs = [{
        'message': n['message'],
        'time': n['timestamp'].strftime('%H:%M'),
        'read': n['read']
    } for n in dashboard['notifications']]
    unread = sum(1 for n in carer.notifications if not n['read'])
    return jsonify({
        'total_missed_7day': dashboard['total_missed_doses_7day'],
        'average_adherence': round(dashboard['average_adherence'], 1),
        'notifications': notifs,
        'unread_count': unread
    })

# ── Family routes ─────────────────────────────────────────────────────────────
@app.route('/family')
def family_dashboard():
    if session.get('role') != 'family':
        return redirect(url_for('login'))
    dashboard = family.get_dashboard()
    return render_template('family.html', dashboard=dashboard, family=family)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
