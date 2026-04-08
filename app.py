import datetime
import threading
import time
from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from models import Medication, Patient, Carer, PRIORITY_LABELS

app = Flask(__name__)
app.secret_key = 'medication-tracker-secret'

# Create the data objects
carer = Carer('Dior')
patient = Patient('Dorothy', 71)
medication = Medication('Aricept', 3, 2, 4, 23, dose_mg=5, stock_count=30, priority='Critical')
patient.add_medication(medication)
carer.add_patient(patient)

# Simple login credentials
USERS = {
    'dorothy': {'password': '1234', 'role': 'patient'},
    'dior': {'password': '5678', 'role': 'carer'}
}


# ── Background monitoring thread ──────────────────────────────────────────────
def check_for_missed_doses():
    checked_doses = set()
    while True:
        try:
            now = datetime.datetime.now()
            for med in patient.medications:
                for dose_time in med.dose_times:
                    window_end = dose_time + datetime.timedelta(hours=med.window_hours)
                    dose_key = f"{med.name}_{dose_time}"
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


monitor = threading.Thread(target=check_for_missed_doses, daemon=True)
monitor.start()


# ── Auth routes ───────────────────────────────────────────────────────────────
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
            return redirect(url_for('patient_view' if session['role'] == 'patient' else 'carer_view'))
        error = 'Invalid username or password'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Patient routes ────────────────────────────────────────────────────────────
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
            doses.append({'time': dose_time.strftime('%H:%M'), 'status': status})

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
            'priority': med.priority,
            'doses': doses,
            'is_due': is_due
        })

    # Sort by priority so Critical shows first
    priority_order = {'Critical': 0, 'High': 1, 'Routine': 2}
    schedule.sort(key=lambda x: priority_order.get(x['priority'], 99))

    return render_template('patient.html',
                           patient=patient,
                           schedule=schedule,
                           recent_doses=patient.get_recent_doses())


@app.route('/patient/take/<medication_name>', methods=['POST'])
def take_medication(medication_name):
    if session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorised'}), 403

    matched_med = next((m for m in patient.medications if m.name == medication_name), None)
    if matched_med is None:
        return jsonify({'success': False, 'message': 'Medication not found'}), 404
    if not matched_med.is_dose_due_now():
        return jsonify({'success': False, 'message': 'This dose is not due right now'}), 400

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
    if matched_med.is_stock_low():
        carer.add_alert(
            f"LOW STOCK: {patient.name}'s {matched_med.full_label} has only "
            f"{matched_med.stock_count} doses left.",
            alert_type='low_stock'
        )
    return jsonify({'success': True})


# ── Carer routes ──────────────────────────────────────────────────────────────
@app.route('/carer')
def carer_view():
    if session.get('role') != 'carer':
        return redirect(url_for('login'))

    total_taken = len(patient.doses_taken)
    total_missed = len(patient.doses_missed)
    adherence = patient.get_adherence_data(7)

    return render_template('carer.html',
                           carer=carer,
                           patient=patient,
                           total_taken=total_taken,
                           total_missed=total_missed,
                           alerts=carer.alerts[-10:],
                           adherence=adherence,
                           priority_labels=PRIORITY_LABELS)


# ── Medication management (carer only) ───────────────────────────────────────
def _require_carer():
    return session.get('role') == 'carer'


def _parse_med_form(form):
    """Parse and validate medication form fields. Returns (data_dict, error_str)."""
    name = form.get('name', '').strip()
    if not name:
        return None, 'Medication name is required.'

    try:
        doses_per_day = int(form.get('doses_per_day', 1))
        window_hours = int(form.get('window_hours', 2))
        hours_between_doses = int(form.get('hours_between_doses', 8))
        first_dose_hour = int(form.get('first_dose_hour', 8))
        dose_mg_raw = form.get('dose_mg', '').strip()
        dose_mg = float(dose_mg_raw) if dose_mg_raw else None
        stock_raw = form.get('stock_count', '').strip()
        stock_count = int(stock_raw) if stock_raw else None
        low_stock_threshold = int(form.get('low_stock_threshold', 7))
        priority = form.get('priority', 'Routine')
    except ValueError as e:
        return None, f'Invalid value: {e}'

    if doses_per_day < 1 or doses_per_day > 12:
        return None, 'Doses per day must be between 1 and 12.'
    if first_dose_hour < 0 or first_dose_hour > 23:
        return None, 'First dose hour must be 0–23.'

    return {
        'name': name,
        'doses_per_day': doses_per_day,
        'window_hours': window_hours,
        'hours_between_doses': hours_between_doses,
        'first_dose_hour': first_dose_hour,
        'dose_mg': dose_mg,
        'stock_count': stock_count,
        'low_stock_threshold': low_stock_threshold,
        'priority': priority,
    }, None


@app.route('/carer/medication/add', methods=['POST'])
def medication_add():
    if not _require_carer():
        return jsonify({'success': False, 'message': 'Unauthorised'}), 403

    data, error = _parse_med_form(request.form)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    # Check for duplicate name
    if patient.get_medication(data['name']):
        return jsonify({'success': False, 'message': f"A medication named '{data['name']}' already exists."}), 400

    med = Medication(**data)
    patient.add_medication(med)
    return jsonify({'success': True, 'medication': med.to_dict()})


@app.route('/carer/medication/edit/<original_name>', methods=['POST'])
def medication_edit(original_name):
    if not _require_carer():
        return jsonify({'success': False, 'message': 'Unauthorised'}), 403

    med = patient.get_medication(original_name)
    if not med:
        return jsonify({'success': False, 'message': 'Medication not found'}), 404

    data, error = _parse_med_form(request.form)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    # If renaming, check the new name isn't already taken
    if data['name'] != original_name and patient.get_medication(data['name']):
        return jsonify({'success': False, 'message': f"A medication named '{data['name']}' already exists."}), 400

    # Apply changes
    med.name = data['name']
    med.dose_mg = data['dose_mg']
    med.doses_per_day = data['doses_per_day']
    med.window_hours = data['window_hours']
    med.hours_between_doses = data['hours_between_doses']
    med.first_dose_hour = data['first_dose_hour']
    med.stock_count = data['stock_count']
    med.low_stock_threshold = data['low_stock_threshold']
    med.priority = data['priority']
    med.refresh_schedule()

    return jsonify({'success': True, 'medication': med.to_dict()})


@app.route('/carer/medication/delete/<med_name>', methods=['POST'])
def medication_delete(med_name):
    if not _require_carer():
        return jsonify({'success': False, 'message': 'Unauthorised'}), 403

    med = patient.get_medication(med_name)
    if not med:
        return jsonify({'success': False, 'message': 'Medication not found'}), 404

    patient.remove_medication(med_name)
    return jsonify({'success': True})


# ── Adherence API (carer only) ────────────────────────────────────────────────
@app.route('/carer/adherence')
def adherence_api():
    if not _require_carer():
        return jsonify({'error': 'Unauthorised'}), 403
    return jsonify(patient.get_adherence_data(7))


# ── Register ──────────────────────────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('role') != 'carer':
        return redirect(url_for('login'))

    error = None
    success = None
    if request.method == 'POST':
        account_type = request.form.get('account_type')
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        full_name = request.form.get('full_name', '').strip()
        age = request.form.get('age', '').strip()

        if username in USERS:
            error = 'Username already taken.'
        else:
            if account_type == 'patient':
                new_patient = Patient(full_name, int(age))
                carer.add_patient(new_patient)
                USERS[username] = {'password': password, 'role': 'patient'}
            else:
                USERS[username] = {'password': password, 'role': 'carer'}
            success = f"Account created for {full_name}."

    return render_template('register.html', error=error, success=success)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
