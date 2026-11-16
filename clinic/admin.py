from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    Appointment,
    Doctor,
    OperationLog,
    RolePermission,
    Schedule,
    User,
    Visit,
    VisitHistory,
)


@admin.register(User)
class ClinicUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "role", "phone", "is_active")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("门诊资料", {"fields": ("role", "phone", "gender", "birth_date", "address")}),
    )


admin.site.register([Doctor, RolePermission, Schedule, Appointment, Visit, VisitHistory, OperationLog])
admin.site.site_header = "中医门诊预约和医生排班管理系统"
