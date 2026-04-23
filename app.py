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
medication = Medication('Aricept', 3, 2, 4, 23, dose_mg=5, stock_count = 30)
patient.add_medication(medication)
carer.add_patient(patient)
all_patients = [patient]
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

    # 1. Get the username of whoever just logged in
    current_username = session.get('username', '').lower()

    # 2. Find THAT specific patient in our list
    # We match the name you typed in 'Full Name' during registration
    # (assuming username and full name are used consistently)
    current_patient = next((p for p in all_patients if p.name.lower() == current_username), None)

    # 3. If we can't find them, default to the original patient (Dorothy)
    if not current_patient:
        current_patient = patient

    schedule = []
    now = datetime.datetime.now()

    # 4. Use 'current_patient' instead of the hard-coded 'patient'
    for med in current_patient.medications:
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

        # Logic to enable/disable the "Take" button
        is_due = False
        if med.is_dose_due_now():
            for dose_time in med.dose_times:
                window_end = dose_time + datetime.timedelta(hours=med.window_hours)
                if dose_time <= now <= window_end:
                    already_taken = any(
                        d['medication_name'] == med.name and
                        dose_time <= d['time'] <= window_end
                        for d in current_patient.doses_taken
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

    return render_template('patient.html',
                           patient=current_patient,
                           schedule=schedule,
                           recent_doses=current_patient.get_recent_doses())


@app.route('/patient/take/<medication_name>', methods=['POST'])
def take_medication(medication_name):
    if session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorised'}), 403

    # Find the specific patient again
    current_username = session.get('username', '').lower()
    current_patient = next((p for p in all_patients if p.name.lower() == current_username), patient)

    matched_med = next(
        (med for med in current_patient.medications if med.name == medication_name),
        None
    )

    if matched_med is None:
        return jsonify({'success': False, 'message': 'Medication not found'}), 404

    if not matched_med.is_dose_due_now():
        return jsonify({'success': False, 'message': 'This dose is not due right now'}), 400

    # Safety check: Already taken?
    now = datetime.datetime.now()
    already_taken = False
    for dose_time in matched_med.dose_times:
        window_end = dose_time + datetime.timedelta(hours=matched_med.window_hours)
        if dose_time <= now <= window_end:
            already_taken = any(
                d['medication_name'] == matched_med.name and
                dose_time <= d['time'] <= window_end
                for d in current_patient.doses_taken
            )
            break

    if already_taken:
        return jsonify({'success': False, 'message': 'Dose already recorded'}), 400

    current_patient.take_dose(matched_med)

    if matched_med.is_stock_low():
        carer.add_alert(
            f"LOW STOCK: {current_patient.name}'s {matched_med.full_label} has only {matched_med.stock_count} doses left.",
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
                           alerts=carer.alerts[-10:],
                           adherence=patient.get_adherence_data(),
                           priority_labels=PRIORITY_LABELS)


@app.route('/carer/medication/add', methods=['POST'])
def add_medication():
    if session.get('role') != 'carer':
        return jsonify({'success': False, 'message': 'Unauthorised'}), 403

    try:
        new_med = Medication(
            name=request.form.get('name', '').strip(),
            doses_per_day=int(request.form.get('doses_per_day', 1)),
            window_hours=int(request.form.get('window_hours', 2)),
            hours_between_doses=int(request.form.get('hours_between_doses', 8)),
            first_dose_hour=int(request.form.get('first_dose_hour', 8)),
            dose_mg=float(request.form.get('dose_mg')) if request.form.get('dose_mg') else None,
            stock_count=int(request.form.get('stock_count')) if request.form.get('stock_count') else None,
            low_stock_threshold=int(request.form.get('low_stock_threshold', 7)),
            priority=request.form.get('priority', 'Routine')
        )
        patient.add_medication(new_med)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route('/carer/medication/edit/<med_name>', methods=['POST'])
def edit_medication(med_name):
    if session.get('role') != 'carer':
        return jsonify({'success': False, 'message': 'Unauthorised'}), 403

    med = patient.get_medication(med_name)
    if not med:
        return jsonify({'success': False, 'message': 'Medication not found'}), 404

    try:
        med.name = request.form.get('name', med.name).strip()
        med.doses_per_day = int(request.form.get('doses_per_day', med.doses_per_day))
        med.window_hours = int(request.form.get('window_hours', med.window_hours))
        med.hours_between_doses = int(request.form.get('hours_between_doses', med.hours_between_doses))
        med.first_dose_hour = int(request.form.get('first_dose_hour', med.first_dose_hour))
        med.dose_mg = float(request.form.get('dose_mg')) if request.form.get('dose_mg') else None
        med.stock_count = int(request.form.get('stock_count')) if request.form.get('stock_count') else med.stock_count
        med.low_stock_threshold = int(request.form.get('low_stock_threshold', med.low_stock_threshold))
        med.priority = request.form.get('priority', med.priority)
        med.refresh_schedule()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route('/carer/medication/delete/<med_name>', methods=['POST'])
def delete_medication(med_name):
    if session.get('role') != 'carer':
        return jsonify({'success': False, 'message': 'Unauthorised'}), 403

    med = patient.get_medication(med_name)
    if not med:
        return jsonify({'success': False, 'message': 'Medication not found'}), 404

    patient.remove_medication(med_name)
    return jsonify({'success': True})
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Credentials
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('account_type')
        full_name = request.form.get('full_name', '').strip()

        if role == 'patient':
            # 1. Create the Class Objects
            new_patient = Patient(username, int(request.form.get('age', 0)))
            new_med = Medication(
                name=request.form.get('med_name'),
                doses_per_day=int(request.form.get('doses_per_day', 1)),
                window_hours=int(request.form.get('window_hours', 2)),
                hours_between_doses=int(request.form.get('hours_between', 4)),
                first_dose_hour=int(request.form.get('first_dose_hour', 8)),
                dose_mg=int(request.form.get('dose_mg', 0)),
                stock_count=int(request.form.get('stock_count', 0))
            )
            new_patient.add_medication(new_med)
            all_patients.append(new_patient)
            carer.add_patient(new_patient) # Links object to the main Carer instance

            # 2. Add to Login Dictionary
            USERS[username] = {'password': password, 'role': 'patient'}

        elif role == 'family':
            # Just add the login credentials
            # They will see the same dashboard as 'carer'
            USERS[username] = {'password': password, 'role': 'carer'}

        return redirect(url_for('login'))

    return render_template('register.html', patients=carer.patients)
if __name__ == '__main__':
    app.run(debug=True, port=5000)


## to add
# better system for adding patients choosing medictaion etc
#perosnalised name greetings for diff patients
#add fmaily not carer