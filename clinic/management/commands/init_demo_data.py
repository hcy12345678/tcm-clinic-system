from datetime import time, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from clinic.models import (
    Appointment, Doctor, OperationLog, RolePermission, Schedule, User, Visit, VisitHistory
)


class Command(BaseCommand):
    help = "初始化教学演示账号和业务数据（可重复执行）"

    def handle(self, *args, **options):
        for role, _ in User.Role.choices:
            RolePermission.objects.get_or_create(role=role, defaults=RolePermission.defaults_for(role))

        def make_user(username, password, role, name, phone, legacy_username=None):
            """创建或更新演示账号；若存在旧用户名，则原地改名以保留关联业务数据。"""
            user = User.objects.filter(username=username).first()
            if user is None and legacy_username:
                legacy = User.objects.filter(username=legacy_username).first()
                if legacy is not None:
                    legacy.username = username
                    legacy.save(update_fields=["username"])
                    user = legacy
            if user is None:
                user = User(username=username)
            user.set_password(password)
            user.role = role
            user.first_name = name
            user.phone = phone
            user.is_active = True
            if role == User.Role.ADMIN:
                user.is_staff = True
                user.is_superuser = True
            user.save()
            return user

        admin = make_user("gly123", "gly123", User.Role.ADMIN, "系统管理员", "13800000000", legacy_username="admin")
        doctor_user1 = make_user("ys1234", "ys1234", User.Role.DOCTOR, "王医生", "13800000001", legacy_username="doctor")
        doctor_user2 = make_user("doctor2", "ys1234", User.Role.DOCTOR, "李医生", "13800000002")
        doctor_user3 = make_user("doctor3", "ys1234", User.Role.DOCTOR, "陈医生", "13800000003")
        patient1 = make_user("hz1234", "hz1234", User.Role.PATIENT, "张患者", "13900000001", legacy_username="patient")
        patient2 = make_user("patient2", "hz1234", User.Role.PATIENT, "刘患者", "13900000002")

        doctor1, _ = Doctor.objects.update_or_create(
            employee_no="D001",
            defaults={"user": doctor_user1, "department": "中医内科", "title": "主任医师", "specialty": "脾胃调理、慢性病中医诊疗", "introduction": "从事中医内科临床工作，注重辨证施治。"},
        )
        doctor2, _ = Doctor.objects.update_or_create(
            employee_no="D002",
            defaults={"user": doctor_user2, "department": "针灸推拿科", "title": "主治医师", "specialty": "针灸、推拿、颈肩腰腿痛调理", "introduction": "擅长针灸与传统推拿疗法。"},
        )
        doctor3, _ = Doctor.objects.update_or_create(
            employee_no="D003",
            defaults={"user": doctor_user3, "department": "中医妇科", "title": "副主任医师", "specialty": "中医体质调理、妇科常见病", "introduction": "开展中医妇科与体质健康指导。"},
        )

        today = timezone.localdate()

        def make_schedule(doctor, days, start, end, room, slots=20):
            schedule, _ = Schedule.objects.get_or_create(
                doctor=doctor, date=today + timedelta(days=days), start_time=start,
                defaults={"end_time": end, "room": room, "total_slots": slots},
            )
            schedule.end_time = end
            schedule.room = room
            schedule.total_slots = slots
            schedule.status = Schedule.Status.OPEN
            schedule.save()
            return schedule

        s1 = make_schedule(doctor1, 0, time(8, 30), time(11, 30), "一楼 101 诊室")
        s2 = make_schedule(doctor1, 1, time(14, 0), time(17, 0), "一楼 101 诊室", 15)
        s3 = make_schedule(doctor2, 0, time(9, 0), time(12, 0), "二楼 203 诊室", 12)
        s4 = make_schedule(doctor2, 2, time(8, 30), time(11, 30), "二楼 203 诊室", 12)
        make_schedule(doctor3, 1, time(8, 30), time(11, 30), "三楼 305 诊室", 18)
        make_schedule(doctor3, 3, time(14, 0), time(17, 0), "三楼 305 诊室", 18)

        def make_appointment(number, patient, schedule, symptoms, status):
            appointment, _ = Appointment.objects.get_or_create(
                appointment_no=number,
                defaults={"patient": patient, "schedule": schedule, "symptoms": symptoms, "status": status},
            )
            return appointment

        a1 = make_appointment("YY20260001", patient1, s1, "食欲不佳，容易疲倦。", Appointment.Status.COMPLETED)
        make_appointment("YY20260002", patient2, s4, "颈肩酸胀，希望进行推拿调理。", Appointment.Status.BOOKED)
        make_appointment("YY20260003", patient1, s2, "睡眠欠佳，想进行中医体质调理。", Appointment.Status.BOOKED)
        make_appointment("YY20260004", patient2, s3, "临时有事，已取消本次预约。", Appointment.Status.CANCELLED)

        visit, created = Visit.objects.get_or_create(
            appointment=a1,
            defaults={
                "diagnosis": "脾虚湿困", "treatment": "健脾祛湿，配合饮食作息调理。",
                "prescription": "教学模拟处方，不作为真实诊疗依据。", "status": Visit.Status.FINISHED,
                "note": "演示数据，无异常情况。", "operator": doctor_user1,
            },
        )
        if created:
            VisitHistory.objects.create(visit=visit, action="创建就诊登记", note="初始化模拟记录", operator=doctor_user1)
            VisitHistory.objects.create(visit=visit, action="状态更新为已完成", note="完成本次模拟接诊", operator=doctor_user1)
        if not OperationLog.objects.exists():
            OperationLog.objects.create(operator=admin, module="用户与权限", action="初始化", object_id="demo", detail="初始化教学演示数据")
        self.stdout.write(self.style.SUCCESS("演示数据初始化完成。"))
        self.stdout.write("管理员：gly123 / gly123")
        self.stdout.write("医师：ys1234 / ys1234")
        self.stdout.write("患者：hz1234 / hz1234")
