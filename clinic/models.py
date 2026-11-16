from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "管理员"
        DOCTOR = "DOCTOR", "医师"
        PATIENT = "PATIENT", "患者"

    role = models.CharField("角色", max_length=10, choices=Role.choices, default=Role.PATIENT)
    phone = models.CharField("联系电话", max_length=20, blank=True)
    gender = models.CharField(
        "性别", max_length=1, choices=[("M", "男"), ("F", "女")], blank=True
    )
    birth_date = models.DateField("出生日期", null=True, blank=True)
    address = models.CharField("联系地址", max_length=200, blank=True)

    @property
    def display_name(self):
        return self.first_name or self.username


class RolePermission(models.Model):
    role = models.CharField("角色", max_length=10, choices=User.Role.choices, primary_key=True)
    can_user = models.BooleanField("用户与权限管理", default=False)
    can_schedule = models.BooleanField("医师排班", default=True)
    can_appointment = models.BooleanField("预约挂号", default=True)
    can_visit = models.BooleanField("就诊登记", default=True)
    can_statistics = models.BooleanField("查询统计与日志", default=False)

    class Meta:
        verbose_name = "角色权限"
        verbose_name_plural = verbose_name

    @staticmethod
    def defaults_for(role):
        return {
            "can_user": role == User.Role.ADMIN,
            "can_schedule": True,
            "can_appointment": True,
            "can_visit": True,
            "can_statistics": role in (User.Role.ADMIN, User.Role.DOCTOR),
        }

    def __str__(self):
        return self.get_role_display()


class Doctor(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
        verbose_name="登录账号",
    )
    employee_no = models.CharField("医师工号", max_length=20, unique=True)
    department = models.CharField("科室", max_length=50, default="中医内科")
    title = models.CharField("职称", max_length=50, default="主治医师")
    specialty = models.CharField("擅长诊疗", max_length=200, blank=True)
    introduction = models.TextField("医师简介", blank=True)
    is_active = models.BooleanField("是否出诊", default=True)

    class Meta:
        verbose_name = "医师"
        verbose_name_plural = verbose_name
        ordering = ["employee_no"]

    def __str__(self):
        return f"{self.user.display_name}（{self.department}）"


class Schedule(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "开放预约"
        STOPPED = "STOPPED", "暂停预约"

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="schedules", verbose_name="出诊医师")
    date = models.DateField("出诊日期")
    start_time = models.TimeField("开始时间")
    end_time = models.TimeField("结束时间")
    room = models.CharField("诊室", max_length=50, default="一楼 101 诊室")
    total_slots = models.PositiveIntegerField("号源数量", default=20)
    status = models.CharField("排班状态", max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "医师排班"
        verbose_name_plural = verbose_name
        ordering = ["-date", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "date", "start_time"], name="unique_doctor_schedule"
            )
        ]

    @property
    def booked_slots(self):
        return self.appointments.exclude(status=Appointment.Status.CANCELLED).count()

    @property
    def remaining_slots(self):
        return max(self.total_slots - self.booked_slots, 0)

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError("结束时间必须晚于开始时间。")

    def __str__(self):
        return f"{self.doctor.user.display_name} {self.date} {self.start_time:%H:%M}"


class Appointment(models.Model):
    class Status(models.TextChoices):
        BOOKED = "BOOKED", "已预约"
        CANCELLED = "CANCELLED", "已取消"
        COMPLETED = "COMPLETED", "已完成"

    appointment_no = models.CharField("预约编号", max_length=30, unique=True, editable=False, blank=True)
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointments",
        limit_choices_to={"role": User.Role.PATIENT},
        verbose_name="患者",
    )
    schedule = models.ForeignKey(
        Schedule, on_delete=models.PROTECT, related_name="appointments", verbose_name="预约排班"
    )
    symptoms = models.TextField("症状描述", blank=True)
    status = models.CharField("预约状态", max_length=12, choices=Status.choices, default=Status.BOOKED)
    created_at = models.DateTimeField("预约时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "预约挂号"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def clean(self):
        if self.schedule_id and self.status != self.Status.CANCELLED:
            active_count = self.schedule.appointments.exclude(status=self.Status.CANCELLED).exclude(pk=self.pk).count()
            if active_count >= self.schedule.total_slots:
                raise ValidationError("该排班的号源已约满，请选择其他排班。")
            if self.schedule.status != Schedule.Status.OPEN and not self.pk:
                raise ValidationError("该排班已暂停预约。")

    def save(self, *args, **kwargs):
        if not self.appointment_no:
            self.appointment_no = f"YY{timezone.now():%Y%m%d%H%M%S%f}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.appointment_no


class Visit(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "待接诊"
        IN_PROGRESS = "IN_PROGRESS", "就诊中"
        FINISHED = "FINISHED", "已完成"
        CANCELLED = "CANCELLED", "已取消"

    appointment = models.OneToOneField(
        Appointment, on_delete=models.PROTECT, related_name="visit", verbose_name="预约记录"
    )
    visit_time = models.DateTimeField("就诊时间", default=timezone.now)
    diagnosis = models.TextField("中医诊断", blank=True)
    treatment = models.TextField("治疗方案", blank=True)
    prescription = models.TextField("处方建议", blank=True)
    status = models.CharField("就诊状态", max_length=12, choices=Status.choices, default=Status.PENDING)
    note = models.TextField("异常备注", blank=True)
    attachment = models.FileField("附件", upload_to="visit_attachments/%Y/%m/", blank=True)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="handled_visits", verbose_name="经办人"
    )
    created_at = models.DateTimeField("登记时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "就诊登记"
        verbose_name_plural = verbose_name
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.appointment.appointment_no} 就诊记录"


class VisitHistory(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="histories", verbose_name="就诊记录")
    action = models.CharField("操作", max_length=50)
    note = models.CharField("留痕说明", max_length=300, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="操作人")
    created_at = models.DateTimeField("操作时间", auto_now_add=True)

    class Meta:
        verbose_name = "就诊历史"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]


class OperationLog(models.Model):
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operation_logs",
        verbose_name="操作人",
    )
    module = models.CharField("功能模块", max_length=30)
    action = models.CharField("操作类型", max_length=50)
    object_id = models.CharField("业务对象", max_length=100, blank=True)
    detail = models.CharField("操作详情", max_length=300, blank=True)
    ip_address = models.GenericIPAddressField("IP地址", null=True, blank=True)
    created_at = models.DateTimeField("操作时间", auto_now_add=True)

    class Meta:
        verbose_name = "操作日志"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.module} - {self.action}"
