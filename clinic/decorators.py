from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from .models import RolePermission, User


def menu_required(field):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.role == User.Role.ADMIN:
                return view_func(request, *args, **kwargs)
            permission, _ = RolePermission.objects.get_or_create(
                role=request.user.role,
                defaults=RolePermission.defaults_for(request.user.role),
            )
            if not getattr(permission, field):
                raise PermissionDenied("当前角色没有访问此功能的权限。")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def staff_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.role not in (User.Role.ADMIN, User.Role.DOCTOR):
            raise PermissionDenied("仅医师或管理员可以执行此操作。")
        return view_func(request, *args, **kwargs)

    return wrapper
