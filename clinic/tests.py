from datetime import time, timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Appointment, Doctor, OperationLog, RolePermission, Schedule, User, Visit


class ClinicFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for role, _ in User.Role.choices:
            RolePermission.objects.create(role=role, **RolePermission.defaults_for(role))
        cls.admin = User.objects.create_user("admin", password="Admin123456", role=User.Role.ADMIN, first_name="管理员")
        cls.doctor_user = User.objects.create_user("doctor", password="Doctor123456", role=User.Role.DOCTOR, first_name="王医生")
        cls.patient = User.objects.create_user("patient", password="Patient123456", role=User.Role.PATIENT, first_name="张患者")
        cls.doctor = Doctor.objects.create(user=cls.doctor_user, employee_no="D001", department="中医内科")
        cls.schedule = Schedule.objects.create(
            doctor=cls.doctor, date=timezone.localdate() + timedelta(days=1),
            start_time=time(8, 30), end_time=time(11, 30), total_slots=5,
        )

    def login(self, user, password):
        self.client.force_login(user)

    def test_login_page_and_logout(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.login(username="admin", password="Admin123456"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_admin_can_open_five_modules(self):
        self.client.force_login(self.admin)
        for name in ("user_list", "permissions", "schedule_list", "appointment_list", "visit_list", "statistics", "operation_logs"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_patient_permission_is_enforced(self):
        self.client.force_login(self.patient)
        self.assertEqual(self.client.get(reverse("user_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("statistics")).status_code, 403)
        self.assertEqual(self.client.get(reverse("appointment_list")).status_code, 200)

    def test_schedule_create_edit_detail_and_delete(self):
        self.client.force_login(self.admin)
        data = {
            "doctor": self.doctor.pk, "date": timezone.localdate() + timedelta(days=3),
            "start_time": "14:00", "end_time": "17:00", "room": "101", "total_slots": 8,
            "status": Schedule.Status.OPEN,
        }
        response = self.client.post(reverse("schedule_create"), data)
        self.assertEqual(response.status_code, 302)
        schedule = Schedule.objects.get(date=data["date"])
        self.assertEqual(self.client.get(reverse("schedule_detail", args=[schedule.pk])).status_code, 200)
        data["room"] = "102"
        self.client.post(reverse("schedule_edit", args=[schedule.pk]), data)
        schedule.refresh_from_db()
        self.assertEqual(schedule.room, "102")
        self.client.post(reverse("schedule_delete", args=[schedule.pk]))
        self.assertFalse(Schedule.objects.filter(pk=schedule.pk).exists())

    def test_patient_creates_and_cancels_appointment(self):
        self.client.force_login(self.patient)
        response = self.client.post(reverse("appointment_create"), {"schedule": self.schedule.pk, "symptoms": "测试症状"})
        self.assertEqual(response.status_code, 302)
        appointment = Appointment.objects.get(patient=self.patient)
        self.assertTrue(appointment.appointment_no.startswith("YY"))
        self.client.post(reverse("appointment_cancel", args=[appointment.pk]))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CANCELLED)
        self.assertEqual(self.schedule.remaining_slots, 5)

    def test_doctor_handles_visit_and_history(self):
        appointment = Appointment.objects.create(patient=self.patient, schedule=self.schedule, symptoms="测试")
        self.client.force_login(self.doctor_user)
        response = self.client.post(reverse("visit_create"), {
            "appointment": appointment.pk, "visit_time": "2026-11-12T09:00",
            "diagnosis": "模拟诊断", "treatment": "模拟治疗", "prescription": "模拟处方",
            "status": Visit.Status.FINISHED, "note": "", "history_note": "测试完成",
        })
        self.assertEqual(response.status_code, 302)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)
        self.assertEqual(appointment.visit.histories.count(), 1)

    def test_statistics_and_csv_export(self):
        Appointment.objects.create(patient=self.patient, schedule=self.schedule)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("statistics"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["stats"]["total_appointments"], 1)
        self.assertTrue(response.context["chart_data"]["trend_labels"])
        self.assertEqual(response.context["chart_data"]["department_labels"], ["中医内科"])
        exported = self.client.get(reverse("export_appointments"))
        self.assertEqual(exported.status_code, 200)
        self.assertIn("text/csv", exported["Content-Type"])
        self.assertIn("预约编号", exported.content.decode("utf-8-sig"))

    def test_operations_are_logged(self):
        self.client.force_login(self.patient)
        self.client.post(reverse("appointment_create"), {"schedule": self.schedule.pk, "symptoms": "日志测试"})
        self.assertTrue(OperationLog.objects.filter(module="预约挂号", action="创建预约").exists())

    def test_patient_registration(self):
        response = self.client.post(reverse("register"), {
            "username": "newpatient", "first_name": "新患者", "phone": "13900000000",
            "password1": "TestPass123456", "password2": "TestPass123456",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newpatient")
        self.assertEqual(user.role, User.Role.PATIENT)

    def test_permission_checkbox_value_is_saved(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("permissions"), {"PATIENT_can_appointment": "1"})
        self.assertEqual(response.status_code, 302)
        permission = RolePermission.objects.get(role=User.Role.PATIENT)
        self.assertTrue(permission.can_appointment)
        self.assertFalse(permission.can_user)

    def test_log_list_and_print_report(self):
        Appointment.objects.create(patient=self.patient, schedule=self.schedule)
        OperationLog.objects.create(
            operator=self.admin, module="预约挂号", action="测试操作", object_id="YYTEST", detail="测试详情"
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("operation_logs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "测试操作")
        self.assertEqual(self.client.get(reverse("print_report")).status_code, 200)
