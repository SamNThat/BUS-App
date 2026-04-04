import datetime
import time
import threading


class Medication:
    def __init__(self, med_name, frequency, time_window, interval, first_take):
        self.med_name = med_name
        self.frequency = frequency
        self.time_window = time_window
        self.interval = interval
        self.first_take = first_take
        self.medication_timings = []
        self.generate_today_schedule()

    def generate_today_schedule(self):
        today = datetime.datetime.now().date()
        first_time = datetime.datetime.combine(today, datetime.time(self.first_take, 0))
        self.medication_timings = [first_time]

        for i in range(1, self.frequency):
            next_time = self.medication_timings[i - 1] + datetime.timedelta(hours=self.interval)
            self.medication_timings.append(next_time)

    def is_window_open(self):
        now = datetime.datetime.now()
        for dose_time in self.medication_timings:
            window_end = dose_time + datetime.timedelta(hours=self.time_window)
            if dose_time <= now <= window_end:
                return True, dose_time
        return False, None

    def was_dose_on_time(self, timestamp):
        for dose_time in self.medication_timings:
            window_end = dose_time + datetime.timedelta(hours=self.time_window)
            if dose_time <= timestamp <= window_end:
                return True
        return False


class Patient:
    def __init__(self, name, condition, patient_id, age):
        self.name = name
        self.age = age
        self.condition = condition
        self.patient_id = patient_id
        self.family = []
        self.medication = []
        self.is_logged_in = False
        self.missed_doses = []
        self.taken_doses = []

    def add_family(self, family):
        self.family.append(family)

    def add_med(self, med):
        self.medication.append(med)

    def login(self):
        self.is_logged_in = True

    def logout(self):
        self.is_logged_in = False

    def record_medication_taken(self, med):
        self.taken_doses.append({
            'medication': med,
            'timestamp': datetime.datetime.now(),
            'was_on_time': med.was_dose_on_time(datetime.datetime.now())
        })

    def record_missed_dose(self, med, missed_time):
        self.missed_doses.append({
            'medication': med,
            'missed_time': missed_time
        })

    def get_active_notifications(self):
        """Frontend calls this to get notifications to display"""
        notifications = []
        for med in self.medication:
            is_open, dose_time = med.is_window_open()
            if is_open:
                window_end = dose_time + datetime.timedelta(hours=med.time_window)
                time_left = (window_end - datetime.datetime.now()).total_seconds() / 60
                notifications.append({
                    'medication': med.med_name,
                    'dose_time': dose_time.strftime('%H:%M'),
                    'time_left_minutes': int(time_left),
                    'med_object': med
                })
        return notifications

    def get_adherence(self, days=7):
        if not self.taken_doses:
            return 0.0

        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        recent_doses = [d for d in self.taken_doses if d['timestamp'] > cutoff]

        if not recent_doses:
            return 0.0

        on_time = sum(1 for d in recent_doses if d['was_on_time'])
        return (on_time / len(recent_doses)) * 100

    def get_missed_summary(self, days=7):
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        recent_missed = [d for d in self.missed_doses if d['missed_time'] > cutoff]

        summary = {'total_missed': len(recent_missed), 'by_medication': {}}

        for missed in recent_missed:
            med_name = missed['medication'].med_name
            summary['by_medication'][med_name] = summary['by_medication'].get(med_name, 0) + 1

        return summary


class Family:
    def __init__(self, name, relation, email):
        self.name = name
        self.relation = relation
        self.email = email
        self.patient = None
        self.is_logged_in = False

    def login(self):
        self.is_logged_in = True

    def logout(self):
        self.is_logged_in = False

    def get_dashboard(self):
        if not self.is_logged_in or not self.patient:
            return None

        return {
            'patient_name': self.patient.name,
            'condition': self.patient.condition,
            'age': self.patient.age,
            'adherence_7day': self.patient.get_adherence(7),
            'adherence_30day': self.patient.get_adherence(30),
            'missed_7day': self.patient.get_missed_summary(7),
            'total_doses_taken': len(self.patient.taken_doses),
            'total_doses_missed': len(self.patient.missed_doses)
        }


class Carer:
    def __init__(self, carer_id, email):
        self.carer_id = carer_id
        self.email = email
        self.patients = []
        self.is_logged_in = False

    def add_patient(self, patient):
        self.patients.append(patient)

    def login(self):
        self.is_logged_in = True

    def logout(self):
        self.is_logged_in = False

    def get_dashboard(self):
        if not self.is_logged_in:
            return None

        patients_data = []
        total_missed = 0

        for patient in self.patients:
            patient_info = {
                'patient_name': patient.name,
                'condition': patient.condition,
                'age': patient.age,
                'adherence_7day': patient.get_adherence(7),
                'adherence_30day': patient.get_adherence(30),
                'missed_7day': patient.get_missed_summary(7),
                'total_medications': len(patient.medication),
                'total_doses_taken': len(patient.taken_doses),
                'total_doses_missed': len(patient.missed_doses)
            }
            patients_data.append(patient_info)
            total_missed += patient_info['missed_7day']['total_missed']

        avg_adherence = sum(p['adherence_7day'] for p in patients_data) / len(patients_data) if patients_data else 0

        return {
            'carer_id': self.carer_id,
            'patients': patients_data,
            'total_patients': len(self.patients),
            'total_missed_doses_7day': total_missed,
            'average_adherence': avg_adherence
        }


def monitor_medication_windows(patient, carer):
    """Background process - checks every 60 seconds if doses missed"""
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
                        d['timestamp'] >= dose_time and
                        d['timestamp'] <= window_end
                        for d in patient.taken_doses
                    )

                    if not dose_taken:
                        patient.record_missed_dose(med, dose_time)
                        print(f"📧 EMAIL to {carer.email}: {patient.name} missed {med.med_name}")

                    tracked_windows[window_key] = True

        time.sleep(60)


def setup():
    C1 = Carer(1, "carer@example.com")
    P1 = Patient('Doris', 'Dementia', 1, 71)
    C1.add_patient(P1)

    F1 = Family('James', 'Son', "james@example.com")
    F1.patient = P1
    P1.add_family(F1)

    M1 = Medication('Aricept', 3, 2, 4, 9)
    P1.add_med(M1)

    return C1, P1, F1


def patient_interface(patient):
    patient.login()
    print(f"\n✓ {patient.name} logged in\n")

    while True:
        print("Medication Schedule:")
        print("=" * 40)

        for med in patient.medication:
            print(f"\n{med.med_name}:")
            for i, dose_time in enumerate(med.medication_timings):
                window_end = dose_time + datetime.timedelta(hours=med.time_window)
                now = datetime.datetime.now()

                if dose_time <= now <= window_end:
                    status = "🔔 TAKE NOW"
                elif now > window_end:
                    status = "❌ Missed"
                else:
                    status = "⏰ Later"

                print(f"  Dose {i + 1}: {dose_time.strftime('%H:%M')} {status}")

        print("\n1. Refresh\n2. Logout")
        choice = input("Option: ")

        if choice == "2":
            patient.logout()
            break


def carer_interface(carer):
    carer.login()
    print(f"\n✓ Carer logged in\n")

    while True:
        dashboard = carer.get_dashboard()
        print(f"Patients: {dashboard['total_patients']}")
        print(f"Avg adherence: {dashboard['average_adherence']:.1f}%")
        print(f"Missed (7d): {dashboard['total_missed_doses_7day']}\n")

        for p in dashboard['patients']:
            print(f"  {p['patient_name']}: {p['adherence_7day']:.1f}% - {p['missed_7day']['total_missed']} missed")

        print("\n1. Refresh\n2. Logout")
        choice = input("Option: ")

        if choice == "2":
            carer.logout()
            break


def family_interface(family):
    family.login()
    print(f"\n✓ {family.name} logged in\n")

    while True:
        dashboard = family.get_dashboard()
        print(f"Patient: {dashboard['patient_name']}")
        print(f"7-day adherence: {dashboard['adherence_7day']:.1f}%")
        print(f"30-day adherence: {dashboard['adherence_30day']:.1f}%")
        print(f"Missed (7d): {dashboard['missed_7day']['total_missed']}\n")

        print("1. Refresh\n2. Logout")
        choice = input("Option: ")

        if choice == "2":
            family.logout()
            break


if __name__ == "__main__":
    C1, P1, F1 = setup()

    monitor_thread = threading.Thread(target=monitor_medication_windows, args=(P1, C1), daemon=True)
    monitor_thread.start()

    while True:
        print("\n" + "=" * 40)
        print("MEDICATION SYSTEM")
        print("=" * 40)
        print("1. Patient (Doris)")
        print("2. Carer")
        print("3. Family")
        print("4. Exit")

        choice = input("Select: ")

        if choice == "1":
            patient_interface(P1)
        elif choice == "2":
            carer_interface(C1)
        elif choice == "3":
            family_interface(F1)
        elif choice == "4":
            break
