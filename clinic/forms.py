from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models import Q
from django.utils import timezone
from .models import Appointment, Doctor, Schedule, User, Visit


class BootstrapFormMixin:
    def apply_bootstrap(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    username = forms.CharField(label="登录账号")
    password = forms.CharField(label="登录密码", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_bootstrap()


class RegisterForm(BootstrapFormMixin, UserCreationForm):
    first_name = forms.CharField(label="姓名", max_length=30)
    phone = forms.CharField(label="联系电话", max_length=20, required=False)

    class Meta:
        model = User
        fields = ("username", "first_name", "phone", "password1", "password2")
        labels = {"username": "登录账号"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].min_length = 5
        self.fields["username"].widget.attrs["minlength"] = 5
        self.fields["username"].help_text = "至少5个字符，仅限字母、数字和 @/./+/-/_ 。"
        self.fields["password1"].widget.attrs["minlength"] = 5
        self.fields["password1"].help_text = "至少5个字符，建议包含字母和数字。"
        self.apply_bootstrap()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.PATIENT
        if commit:
            user.save()
        return user


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    first_name = forms.CharField(label="姓名", max_length=30)

    class Meta:
        model = User
        fields = ("first_name", "phone", "gender", "birth_date", "email", "address")
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_bootstrap()


class AdminUserForm(ProfileForm):
    class Meta(ProfileForm.Meta):
        fields = ProfileForm.Meta.fields + ("role", "is_active")


class ScheduleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Schedule
        fields = ("doctor", "date", "start_time", "end_time", "room", "total_slots", "status")
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doctor"].queryset = Doctor.objects.filter(is_active=True).select_related("user")
        self.apply_bootstrap()


class AppointmentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ("patient", "schedule", "symptoms", "status")
        widgets = {"symptoms": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        schedules = Schedule.objects.filter(status=Schedule.Status.OPEN, date__gte=timezone.localdate())
        if self.instance.pk:
            schedules = Schedule.objects.filter(Q(pk=self.instance.schedule_id) | Q(pk__in=schedules))
        self.fields["schedule"].queryset = schedules.select_related("doctor__user")
        self.fields["schedule"].label_from_instance = (
            lambda obj: f"{obj.date} {obj.start_time:%H:%M}｜{obj.doctor.user.display_name}｜余号 {obj.remaining_slots}"
        )
        self.fields["patient"].queryset = User.objects.filter(role=User.Role.PATIENT, is_active=True)
        if user and user.role == User.Role.PATIENT:
            self.instance.patient = user
            self.fields.pop("patient")
            self.fields.pop("status")
        self.apply_bootstrap()


class VisitForm(BootstrapFormMixin, forms.ModelForm):
    history_note = forms.CharField(label="本次操作说明", required=False, max_length=300)

    class Meta:
        model = Visit
        fields = (
            "appointment",
            "visit_time",
            "diagnosis",
            "treatment",
            "prescription",
            "status",
            "note",
            "attachment",
            "history_note",
        )
        widgets = {
            "visit_time": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "diagnosis": forms.Textarea(attrs={"rows": 3}),
            "treatment": forms.Textarea(attrs={"rows": 3}),
            "prescription": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        appointments = Appointment.objects.filter(
            status=Appointment.Status.BOOKED, visit__isnull=True
        ).select_related("patient", "schedule__doctor__user")
        if self.instance.pk:
            appointments = Appointment.objects.filter(
                Q(pk=self.instance.appointment_id) | Q(pk__in=appointments)
            ).select_related("patient", "schedule__doctor__user")
        if user and user.role == User.Role.DOCTOR and hasattr(user, "doctor_profile"):
            appointments = appointments.filter(schedule__doctor=user.doctor_profile)
        self.fields["appointment"].queryset = appointments
        self.fields["appointment"].label_from_instance = (
            lambda obj: f"{obj.appointment_no}｜{obj.patient.display_name}｜{obj.schedule.doctor.user.display_name}"
        )
        self.apply_bootstrap()
