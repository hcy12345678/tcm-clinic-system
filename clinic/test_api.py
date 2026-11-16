"""前后端分离版接口测试：验证 JSON 接口、权限、状态同步与导出。"""

import json
from datetime import time, timedelta

from django.test import TestCase
from django.utils import timezone

from .models import Appointment, Doctor, OperationLog, RolePermission, Schedule, User, Visit, VisitHistory


class ApiTestBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="gly123", password="gly123", first_name="管理员", role=User.Role.ADMIN, is_staff=True
        )
        self.doctor_user = User.objects.create_user(
            username="ys1234", password="ys1234", first_name="王医生", role=User.Role.DOCTOR
        )
        self.doctor = Doctor.objects.create(
            user=self.doctor_user, employee_no="D001", department="中医内科", title="主任医师"
        )
        self.patient = User.objects.create_user(
            username="hz1234", password="hz1234", first_name="张患者", role=User.Role.PATIENT
        )
        self.schedule = Schedule.objects.create(
            doctor=self.doctor,
            date=timezone.localdate() + timedelta(days=1),
            start_time=time(9, 0),
            end_time=time(11, 0),
            room="一楼 101 诊室",
            total_slots=2,
        )
        RolePermission.objects.create(
            role=User.Role.DOCTOR,
            can_user=False, can_schedule=True, can_appointment=True, can_visit=True, can_statistics=True,
        )
        RolePermission.objects.create(
            role=User.Role.PATIENT,
            can_user=False, can_schedule=True, can_appointment=True, can_visit=True, can_statistics=False,
        )

    def post_json(self, url, data):
        return self.client.post(url, data=json.dumps(data), content_type="application/json")

    def put_json(self, url, data):
        return self.client.put(url, data=json.dumps(data), content_type="application/json")

    def payload(self, response):
        return json.loads(response.content.decode("utf-8"))


class AuthApiTests(ApiTestBase):
    def test_me_anonymous_and_login(self):
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.payload(response)["data"]["authenticated"])
        self.assertIn("csrftoken", response.cookies)

        response = self.post_json("/api/auth/login/", {"username": "gly123", "password": "gly123"})
        self.assertEqual(response.status_code, 200)
        body = self.payload(response)
        self.assertTrue(body["data"]["user"]["username"] == "gly123")
        self.assertTrue(body["data"]["perms"]["can_statistics"])

    def test_login_with_wrong_password(self):
        response = self.post_json("/api/auth/login/", {"username": "gly123", "password": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_patient_blocked_by_permission(self):
        self.client.force_login(self.patient)
        response = self.client.get("/api/users/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.payload(response)["code"], "FORBIDDEN")

    def test_patient_can_read_own_appointments_only(self):
        other = User.objects.create_user(username="hz9999", password="hz123456", role=User.Role.PATIENT)
        mine = Appointment.objects.create(patient=self.patient, schedule=self.schedule)
        Appointment.objects.create(patient=other, schedule=self.schedule)
        self.client.force_login(self.patient)
        response = self.client.get("/api/appointments/")
        rows = self.payload(response)["data"]["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["appointment_no"], mine.appointment_no)


class ScheduleApiTests(ApiTestBase):
    def test_create_update_delete_schedule(self):
        self.client.force_login(self.admin)
        response = self.post_json("/api/schedules/", {
            "doctor": self.doctor.id,
            "date": (timezone.localdate() + timedelta(days=2)).isoformat(),
            "start_time": "14:00",
            "end_time": "16:00",
            "room": "二楼 205 诊室",
            "total_slots": 12,
            "status": "OPEN",
        })
        self.assertEqual(response.status_code, 201)
        schedule_id = self.payload(response)["data"]["id"]

        response = self.put_json(f"/api/schedules/{schedule_id}/", {
            "doctor": self.doctor.id,
            "date": (timezone.localdate() + timedelta(days=2)).isoformat(),
            "start_time": "14:00",
            "end_time": "17:00",
            "room": "二楼 206 诊室",
            "total_slots": 15,
            "status": "OPEN",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payload(response)["data"]["total_slots"], 15)

        response = self.client.delete(f"/api/schedules/{schedule_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Schedule.objects.filter(pk=schedule_id).exists())

    def test_invalid_time_range_rejected(self):
        self.client.force_login(self.admin)
        response = self.post_json("/api/schedules/", {
            "doctor": self.doctor.id,
            "date": (timezone.localdate() + timedelta(days=3)).isoformat(),
            "start_time": "16:00",
            "end_time": "15:00",
            "room": "一楼 101 诊室",
            "total_slots": 10,
            "status": "OPEN",
        })
        self.assertEqual(response.status_code, 400)

    def test_delete_schedule_with_appointments_rejected(self):
        Appointment.objects.create(patient=self.patient, schedule=self.schedule)
        self.client.force_login(self.admin)
        response = self.client.delete(f"/api/schedules/{self.schedule.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.payload(response)["code"], "HAS_APPOINTMENTS")

    def test_patient_cannot_create_schedule(self):
        """患者即使拥有排班菜单权限，也只能查看，不能新增。"""
        self.client.force_login(self.patient)
        response = self.post_json("/api/schedules/", {
            "doctor": self.doctor.id,
            "date": (timezone.localdate() + timedelta(days=4)).isoformat(),
            "start_time": "08:00",
            "end_time": "10:00",
            "room": "越权诊室",
            "total_slots": 5,
            "status": "OPEN",
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Schedule.objects.filter(room="越权诊室").exists())

    def test_doctor_schedule_forced_to_self(self):
        """医师提交他人 ID 也会被强制改回本人。"""
        other_user = User.objects.create_user(
            username="ys9999", password="ys123456", first_name="李医生", role=User.Role.DOCTOR
        )
        other = Doctor.objects.create(user=other_user, employee_no="D002", department="针灸科", title="主治医师")
        self.client.force_login(self.doctor_user)
        response = self.post_json("/api/schedules/", {
            "doctor": other.id,
            "date": (timezone.localdate() + timedelta(days=5)).isoformat(),
            "start_time": "13:00",
            "end_time": "15:00",
            "room": "三楼 301 诊室",
            "total_slots": 8,
            "status": "OPEN",
        })
        self.assertEqual(response.status_code, 201)
        created = Schedule.objects.get(pk=self.payload(response)["data"]["id"])
        self.assertEqual(created.doctor_id, self.doctor.id)


class AppointmentApiTests(ApiTestBase):
    def test_create_and_cancel_appointment(self):
        self.client.force_login(self.patient)
        response = self.post_json("/api/appointments/", {"schedule": self.schedule.id, "symptoms": "失眠多梦"})
        self.assertEqual(response.status_code, 201)
        data = self.payload(response)["data"]
        self.assertTrue(data["appointment_no"].startswith("YY"))
        self.assertEqual(data["schedule"]["remaining_slots"], 1)

        response = self.post_json(f"/api/appointments/{data['id']}/cancel/", {})
        self.assertEqual(response.status_code, 200)
        refreshed = Schedule.objects.get(pk=self.schedule.id)
        self.assertEqual(refreshed.remaining_slots, 2)

    def test_full_slots_rejected(self):
        Appointment.objects.create(patient=self.patient, schedule=self.schedule)
        Appointment.objects.create(
            patient=User.objects.create_user(username="hz8888", password="hz123456", role=User.Role.PATIENT),
            schedule=self.schedule,
        )
        self.client.force_login(self.patient)
        response = self.post_json("/api/appointments/", {"schedule": self.schedule.id})
        self.assertEqual(response.status_code, 400)
        self.assertIn("约满", self.payload(response)["message"])

    def test_cancel_completed_appointment_rejected(self):
        appointment = Appointment.objects.create(patient=self.patient, schedule=self.schedule)
        appointment.status = Appointment.Status.COMPLETED
        appointment.save(update_fields=["status"])
        self.client.force_login(self.patient)
        response = self.post_json(f"/api/appointments/{appointment.id}/cancel/", {})
        self.assertEqual(response.status_code, 400)


class VisitApiTests(ApiTestBase):
    def test_visit_flow_syncs_appointment_status(self):
        appointment = Appointment.objects.create(patient=self.patient, schedule=self.schedule)
        self.client.force_login(self.doctor_user)
        response = self.client.post("/api/visits/", {
            "appointment": appointment.id,
            "visit_time": f"{timezone.localdate().isoformat()}T09:30",
            "diagnosis": "肝郁气滞",
            "treatment": "疏肝解郁",
            "prescription": "逍遥散加减",
            "status": Visit.Status.IN_PROGRESS,
            "note": "",
            "history_note": "首次接诊",
        })
        self.assertEqual(response.status_code, 201)
        visit_id = self.payload(response)["data"]["id"]
        self.assertEqual(VisitHistory.objects.filter(visit_id=visit_id).count(), 1)

        response = self.client.post(f"/api/visits/{visit_id}/", {
            "visit_time": f"{timezone.localdate().isoformat()}T09:30",
            "diagnosis": "肝郁气滞",
            "treatment": "疏肝解郁、养心安神",
            "prescription": "逍遥散合归脾汤加减",
            "status": Visit.Status.FINISHED,
            "note": "服药后略感胃部不适",
            "history_note": "诊疗完成",
        })
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)
        self.assertEqual(VisitHistory.objects.filter(visit_id=visit_id).count(), 2)

    def test_patient_cannot_create_visit(self):
        appointment = Appointment.objects.create(patient=self.patient, schedule=self.schedule)
        self.client.force_login(self.patient)
        response = self.client.post("/api/visits/", {"appointment": appointment.id, "status": "PENDING"})
        self.assertEqual(response.status_code, 403)


class StatisticsApiTests(ApiTestBase):
    def test_statistics_and_export(self):
        appointment = Appointment.objects.create(patient=self.patient, schedule=self.schedule)
        Visit.objects.create(appointment=appointment, operator=self.doctor_user, status=Visit.Status.FINISHED)
        appointment.status = Appointment.Status.COMPLETED
        appointment.save(update_fields=["status"])

        self.client.force_login(self.admin)
        response = self.client.get("/api/statistics/")
        self.assertEqual(response.status_code, 200)
        data = self.payload(response)["data"]
        self.assertEqual(data["stats"]["total_appointments"], 1)
        self.assertEqual(data["stats"]["completed_visits"], 1)
        self.assertEqual(data["chart_data"]["status_labels"], ["已完成"])
        self.assertEqual(len(data["records"]), 1)

        response = self.client.get("/api/statistics/export/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("预约编号", response.content.decode("utf-8-sig"))

    def test_patient_blocked_from_statistics(self):
        self.client.force_login(self.patient)
        self.assertEqual(self.client.get("/api/statistics/").status_code, 403)

    def test_doctor_can_view_own_statistics(self):
        """医师可以看统计，但数据范围收敛到本人排班。"""
        other_user = User.objects.create_user(
            username="ys8888", password="ys123456", first_name="赵医生", role=User.Role.DOCTOR
        )
        other_doctor = Doctor.objects.create(user=other_user, employee_no="D003", department="妇科", title="医师")
        other_schedule = Schedule.objects.create(
            doctor=other_doctor,
            date=timezone.localdate() + timedelta(days=1),
            start_time=time(14, 0),
            end_time=time(16, 0),
            room="四楼 401 诊室",
            total_slots=10,
        )
        Appointment.objects.create(patient=self.patient, schedule=self.schedule)
        Appointment.objects.create(patient=self.patient, schedule=other_schedule)

        RolePermission.objects.update_or_create(
            role=User.Role.DOCTOR,
            defaults={
                "can_user": False, "can_schedule": True, "can_appointment": True,
                "can_visit": True, "can_statistics": True,
            },
        )
        self.client.force_login(self.doctor_user)
        response = self.client.get("/api/statistics/")
        self.assertEqual(response.status_code, 200)
        data = self.payload(response)["data"]
        self.assertEqual(data["stats"]["total_appointments"], 1)
        self.assertEqual(data["chart_data"]["department_labels"], ["中医内科"])

    def test_operation_logs_admin_only(self):
        """操作日志仅管理员可看，医师即使有统计权限也被拒绝。"""
        RolePermission.objects.update_or_create(
            role=User.Role.DOCTOR,
            defaults={
                "can_user": False, "can_schedule": True, "can_appointment": True,
                "can_visit": True, "can_statistics": True,
            },
        )
        self.client.force_login(self.doctor_user)
        self.assertEqual(self.client.get("/api/logs/").status_code, 403)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/logs/").status_code, 200)


class LogAndPermissionApiTests(ApiTestBase):
    def test_operation_log_written(self):
        self.client.force_login(self.patient)
        self.post_json("/api/appointments/", {"schedule": self.schedule.id})
        self.assertTrue(
            OperationLog.objects.filter(module="预约", action="创建预约").exists()
        )
        self.client.force_login(self.admin)
        response = self.client.get("/api/logs/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(self.payload(response)["data"]["count"], 1)

    def test_permission_matrix_saved(self):
        self.client.force_login(self.admin)
        response = self.post_json("/api/permissions/", {
            "roles": [{
                "role": "PATIENT",
                "can_user": False,
                "can_schedule": False,
                "can_appointment": True,
                "can_visit": True,
                "can_statistics": False,
            }]
        })
        self.assertEqual(response.status_code, 200)
        permission = RolePermission.objects.get(role=User.Role.PATIENT)
        self.assertFalse(permission.can_schedule)
        self.assertTrue(permission.can_appointment)

    def test_frontend_pages_served(self):
        for page in ("login.html", "index.html", "statistics.html"):
            response = self.client.get(f"/app/{page}")
            self.assertEqual(response.status_code, 200, page)
