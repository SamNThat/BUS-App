import datetime


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

    def get_schedule_status(self):
        now = datetime.datetime.now()
        schedule = []
        for i, dose_time in enumerate(self.medication_timings):
            window_end = dose_time + datetime.timedelta(hours=self.time_window)
            if dose_time <= now <= window_end:
                status = "due"
            elif now > window_end:
                status = "past"
            else:
                status = "upcoming"
            schedule.append({
                'dose_number': i + 1,
                'time': dose_time.strftime('%H:%M'),
                'window_end': window_end.strftime('%H:%M'),
                'status': status,
                'dose_time_obj': dose_time,
                'window_end_obj': window_end
            })
        return schedule


class Patient:
    def __init__(self, name, condition, patient_id, age):
        self.name = name
        self.age = age
        self.condition = condition
        self.patient_id = patient_id
        self.family = []
        self.medication = []
        self.missed_doses = []
        self.taken_doses = []

    def add_family(self, family):
        self.family.append(family)

    def add_med(self, med):
        self.medication.append(med)

    def record_medication_taken(self, med):
        now = datetime.datetime.now()
        self.taken_doses.append({
            'medication': med,
            'med_name': med.med_name,
            'timestamp': now,
            'was_on_time': med.was_dose_on_time(now)
        })

    def record_missed_dose(self, med, missed_time):
        self.missed_doses.append({
            'medication': med,
            'med_name': med.med_name,
            'missed_time': missed_time
        })

    def get_active_notifications(self):
        notifications = []
        for med in self.medication:
            is_open, dose_time = med.is_window_open()
            if is_open:
                window_end = dose_time + datetime.timedelta(hours=med.time_window)
                time_left = (window_end - datetime.datetime.now()).total_seconds() / 60
                # Check if already taken this window
                already_taken = any(
                    d['medication'] == med and
                    dose_time <= d['timestamp'] <= window_end
                    for d in self.taken_doses
                )
                if not already_taken:
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
            med_name = missed['med_name']
            summary['by_medication'][med_name] = summary['by_medication'].get(med_name, 0) + 1
        return summary

    def get_today_taken(self):
        today = datetime.datetime.now().date()
        return [d for d in self.taken_doses if d['timestamp'].date() == today]


class Family:
    def __init__(self, name, relation, email):
        self.name = name
        self.relation = relation
        self.email = email
        self.patient = None

    def get_dashboard(self):
        if not self.patient:
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
        self.notifications = []

    def add_patient(self, patient):
        self.patients.append(patient)

    def add_notification(self, message):
        self.notifications.append({
            'message': message,
            'timestamp': datetime.datetime.now(),
            'read': False
        })

    def get_dashboard(self):
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

        avg_adherence = (
            sum(p['adherence_7day'] for p in patients_data) / len(patients_data)
            if patients_data else 0
        )

        return {
            'carer_id': self.carer_id,
            'patients': patients_data,
            'total_patients': len(self.patients),
            'total_missed_doses_7day': total_missed,
            'average_adherence': avg_adherence,
            'notifications': self.notifications[-10:]
        }
