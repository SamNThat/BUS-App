import datetime


class Medication:
    """Represents a single medication with its dosing schedule"""

    def __init__(self, name, doses_per_day, window_hours, hours_between_doses, first_dose_hour, dose_mg=None, stock_count = None, low_stock_threshold=7):
        self.name = name
        self.dose_mg = dose_mg          # e.g. 5 (in milligrams)
        self.doses_per_day = doses_per_day
        self.window_hours = window_hours
        self.hours_between_doses = hours_between_doses
        self.first_dose_hour = first_dose_hour
        self.dose_times = []
        self.create_schedule()
        self.stock_count = stock_count
        self.low_stock_threshold = low_stock_threshold

    @property
    def dose_label(self):
        """Human-readable dose string, e.g. '5mg' or just the name if no mg set"""
        if self.dose_mg is not None:
            return f"{self.dose_mg}mg"
        return ""

    @property
    def full_label(self):
        """e.g. 'Aricept 5mg'"""
        if self.dose_mg is not None:
            return f"{self.name} {self.dose_mg}mg"
        return self.name

    def create_schedule(self):
        """Generate today's dose times based on the medication parameters"""
        today = datetime.datetime.now().date()
        first_time = datetime.datetime.combine(today, datetime.time(self.first_dose_hour, 0))
        self.dose_times = [first_time]

        for i in range(1, self.doses_per_day):
            next_time = self.dose_times[i - 1] + datetime.timedelta(hours=self.hours_between_doses)
            self.dose_times.append(next_time)

    def is_dose_due_now(self):
        """Check if medication is currently due"""
        now = datetime.datetime.now()
        for dose_time in self.dose_times:
            window_end = dose_time + datetime.timedelta(hours=self.window_hours)
            if dose_time <= now <= window_end:
                return True
        return False

    #added by will
    def is_stock_low(self):
        return self.stock_count is not None and self.stock_count <= self.low_stock_threshold

    def decrement_stock(self):
        if self.stock_count is not None and self.stock_count > 0:
            self.stock_count -= 1


class Patient:
    """Represents a patient taking medication"""

    def __init__(self, name, age):
        self.name = name
        self.age = age
        self.medications = []
        self.doses_taken = []
        self.doses_missed = []

    def add_medication(self, medication):
        """Add a medication to the patient's list"""
        self.medications.append(medication)

    def take_dose(self, medication):
        """Record that a dose has been taken"""
        record = {
            'medication_name': medication.name,
            'dose_mg': medication.dose_mg,
            'time': datetime.datetime.now()
        }
        medication.decrement_stock()  #added

        self.doses_taken.append(record)

    def record_missed(self, medication, missed_time):
        """Record a missed dose"""
        record = {
            'medication_name': medication.name,
            'dose_mg': medication.dose_mg,
            'time': missed_time
        }
        self.doses_missed.append(record)

    def get_recent_doses(self):
        """Get doses taken today"""
        today = datetime.datetime.now().date()
        return [d for d in self.doses_taken if d['time'].date() == today]


class Carer:
    """Represents a carer monitoring patients"""

    def __init__(self, name):
        self.name = name
        self.patients = []
        self.alerts = []

    def add_patient(self, patient):
        """Add a patient to the carer's list"""
        self.patients.append(patient)

    def add_alert(self, message, alert_type= 'missed_dose'):
        """Add an alert about a missed dose"""
        alert = {
            'message': message,
            'time': datetime.datetime.now(),
            'type': alert_type
        }
        self.alerts.append(alert)
