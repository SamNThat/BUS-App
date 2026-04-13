import datetime
import threading
import time
from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from models import Medication, Patient, Carer

app = Flask(__name__)
app.secret_key = 'medication-tracker-secret'

# Create the data objects
carer = Carer('Dior')
patient = Patient('Dorothy', 71)
medication = Medication('Aricept', 3, 2, 4, 23, dose_mg=5, stock_count = 30)
patient.add_medication(medication)
carer.add_patient(patient)

# Simple login credentials
USERS = {
    'dorothy': {'password': '1234', 'role': 'patient'},
    'dior': {'password': '5678', 'role': 'carer'}
}


# Background monitoring thread
def check_for_missed_doses():
    """Check every minute if doses have been missed"""
    checked_doses = set()

    while True:
        try:
            now = datetime.datetime.now()

            for med in patient.medications:
                for dose_time in med.dose_times:
                    window_end = dose_time + datetime.timedelta(hours=med.window_hours)
                    dose_key = f"{med.name}_{dose_time}"

                    # If window has closed and we haven't checked this dose yet
                    if now > window_end and dose_key not in checked_doses:
                        dose_was_taken = any(
                            d['medication_name'] == med.name and
                            dose_time <= d['time'] <= window_end
                            for d in patient.doses_taken
                        )

                        if not dose_was_taken:
                            patient.record_missed(med, dose_time)
                            alert_message = (
                                f"{patient.name} missed {med.full_label} "
                                f"at {dose_time.strftime('%H:%M')}"
                            )
                            carer.add_alert(alert_message)
                            print(f"Alert: {alert_message}")

                        checked_doses.add(dose_key)

        except Exception as e:
            print(f"Error in monitoring thread: {e}")

        time.sleep(60)


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
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')

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
            for dose_time in med.dose_times:
                window_end = dose_time + datetime.timedelta(hours=med.window_hours)
                if dose_time <= now <= window_end:
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
            'full_label': med.full_label,
            'dose_label': med.dose_label,
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
        return jsonify({'success': False, 'message': 'Unauthorised'}), 403

    # Find the medication
    matched_med = next(
        (med for med in patient.medications if med.name == medication_name),
        None
    )

    if matched_med is None:
        return jsonify({'success': False, 'message': 'Medication not found'}), 404

    if not matched_med.is_dose_due_now():
        return jsonify({'success': False, 'message': 'This dose is not due right now'}), 400

    # Check it hasn't already been taken in this window
    now = datetime.datetime.now()
    for dose_time in matched_med.dose_times:
        window_end = dose_time + datetime.timedelta(hours=matched_med.window_hours)
        if dose_time <= now <= window_end:
            already_taken = any(
                d['medication_name'] == matched_med.name and
                dose_time <= d['time'] <= window_end
                for d in patient.doses_taken
            )
            if already_taken:
                return jsonify({'success': False, 'message': 'Dose already recorded for this window'}), 400
            break

    patient.take_dose(matched_med)
    #added
    if matched_med.is_stock_low():
        carer.add_alert(
            f"LOW STOCK: {patient.name}'s {matched_med.full_label} has only {matched_med.stock_count} doses left.",
            alert_type='low_stock'
        )
    return jsonify({'success': True})


@app.route('/carer')
def carer_view():
    if session.get('role') != 'carer':
        return redirect(url_for('login'))

    total_taken = len(patient.doses_taken)
    total_missed = len(patient.doses_missed)

    return render_template('carer.html',
                           carer=carer,
                           patient=patient,
                           total_taken=total_taken,
                           total_missed=total_missed,
                           alerts=carer.alerts[-10:])

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    success = None

    if request.method == 'POST':
        # Only carers can register new accounts
        if session.get('role') != 'carer':
            return redirect(url_for('login'))

        account_type = request.form.get('account_type')
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        full_name = request.form.get('full_name', '').strip()
        age = request.form.get('age', '').strip()

        # Validation
        if not all([username, password, full_name, age]):
            error = 'All fields are required.'
        elif username in USERS:
            error = 'Username already taken.'
        else:
            try:
                age_int = int(age)
                if account_type == 'patient':
                    new_patient = Patient(full_name, age_int)
                    carer.add_patient(new_patient)
                    USERS[username] = {'password': password, 'role': 'patient'}
                else:
                    USERS[username] = {'password': password, 'role': 'carer'}
                return redirect(url_for('login'))  # Success - redirect to login
            except ValueError:
                error = 'Age must be a valid number.'

    return render_template('register.html', error=error, success=success)
if __name__ == '__main__':
    app.run(debug=True, port=5000)
