import datetime


PRIORITY_LABELS = ['Critical', 'High', 'Routine']


class Medication:
    """Represents a single medication with its dosing schedule"""

    def __init__(self, name, doses_per_day, window_hours, hours_between_doses,
                 first_dose_hour, dose_mg=None, stock_count=None,
                 low_stock_threshold=7, priority='Routine'):
        self.name = name
        self.dose_mg = dose_mg
        self.doses_per_day = doses_per_day
        self.window_hours = window_hours
        self.hours_between_doses = hours_between_doses
        self.first_dose_hour = first_dose_hour
        self.stock_count = stock_count
        self.low_stock_threshold = low_stock_threshold
        self.priority = priority if priority in PRIORITY_LABELS else 'Routine'
        self.dose_times = []
        self.create_schedule()

    @property
    def dose_label(self):
        if self.dose_mg is not None:
            return f"{self.dose_mg}mg"
        return ""

    @property
    def full_label(self):
        if self.dose_mg is not None:
            return f"{self.name} {self.dose_mg}mg"
        return self.name

    def create_schedule(self):
        """Generate today's dose times based on the medication parameters"""
        today = datetime.datetime.now().date()
        first_time = datetime.datetime.combine(today, datetime.time(int(self.first_dose_hour), 0))
        self.dose_times = [first_time]
        for i in range(1, self.doses_per_day):
            next_time = self.dose_times[i - 1] + datetime.timedelta(hours=self.hours_between_doses)
            self.dose_times.append(next_time)

    def refresh_schedule(self):
        """Regenerate schedule after editing parameters"""
        self.create_schedule()

    def is_dose_due_now(self):
        now = datetime.datetime.now()
        for dose_time in self.dose_times:
            window_end = dose_time + datetime.timedelta(hours=self.window_hours)
            if dose_time <= now <= window_end:
                return True
        return False

    def is_stock_low(self):
        return self.stock_count is not None and self.stock_count <= self.low_stock_threshold

    def decrement_stock(self):
        if self.stock_count is not None and self.stock_count > 0:
            self.stock_count -= 1

    def to_dict(self):
        return {
            'name': self.name,
            'dose_mg': self.dose_mg,
            'doses_per_day': self.doses_per_day,
            'window_hours': self.window_hours,
            'hours_between_doses': self.hours_between_doses,
            'first_dose_hour': self.first_dose_hour,
            'stock_count': self.stock_count,
            'low_stock_threshold': self.low_stock_threshold,
            'priority': self.priority,
            'dose_times': [t.strftime('%H:%M') for t in self.dose_times],
            'full_label': self.full_label,
            'dose_label': self.dose_label,
        }


class Patient:
    """Represents a patient taking medication"""

    def __init__(self, name, age):
        self.name = name
        self.age = age
        self.medications = []
        self.doses_taken = []
        self.doses_missed = []

    def add_medication(self, medication):
        self.medications.append(medication)

    def remove_medication(self, med_name):
        self.medications = [m for m in self.medications if m.name != med_name]

    def get_medication(self, med_name):
        return next((m for m in self.medications if m.name == med_name), None)

    def take_dose(self, medication):
        record = {
            'medication_name': medication.name,
            'dose_mg': medication.dose_mg,
            'time': datetime.datetime.now()
        }
        medication.decrement_stock()
        self.doses_taken.append(record)

    def record_missed(self, medication, missed_time):
        record = {
            'medication_name': medication.name,
            'dose_mg': medication.dose_mg,
            'time': missed_time
        }
        self.doses_missed.append(record)

    def get_recent_doses(self):
        today = datetime.datetime.now().date()
        return [d for d in self.doses_taken if d['time'].date() == today]

    def get_adherence_data(self, days=7):
        """Return daily adherence % for the past `days` days."""
        today = datetime.datetime.now().date()
        result = []

        for i in range(days - 1, -1, -1):
            day = today - datetime.timedelta(days=i)
            label = day.strftime('%a %d/%m') if i > 0 else 'Today'

            if i == 0:
                # Today: calculate from live schedule
                total_due = 0
                taken = 0
                now = datetime.datetime.now()
                for med in self.medications:
                    for dose_time in med.dose_times:
                        window_end = dose_time + datetime.timedelta(hours=med.window_hours)
                        if dose_time <= now:
                            total_due += 1
                            was_taken = any(
                                d['medication_name'] == med.name and
                                dose_time <= d['time'] <= window_end
                                for d in self.doses_taken
                            )
                            if was_taken:
                                taken += 1
            else:
                day_taken = [d for d in self.doses_taken if d['time'].date() == day]
                day_missed = [d for d in self.doses_missed if d['time'].date() == day]
                total_due = len(day_taken) + len(day_missed)
                taken = len(day_taken)

            pct = round((taken / total_due * 100) if total_due > 0 else 0)
            result.append({
                'label': label,
                'taken': taken,
                'total': total_due,
                'pct': pct
            })

        return result


class Carer:
    """Represents a carer monitoring patients"""

    def __init__(self, name):
        self.name = name
        self.patients = []
        self.alerts = []

    def add_patient(self, patient):
        self.patients.append(patient)

    def add_alert(self, message, alert_type='missed_dose'):
        alert = {
            'message': message,
            'time': datetime.datetime.now(),
            'type': alert_type
        }
        self.alerts.append(alert)
