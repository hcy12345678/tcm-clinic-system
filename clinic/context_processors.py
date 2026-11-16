from .models import RolePermission


def menu_permissions(request):
    if not request.user.is_authenticated:
        return {"perms": None}
    permission, _ = RolePermission.objects.get_or_create(
        role=request.user.role,
        defaults=RolePermission.defaults_for(request.user.role),
    )
    return {"perms": permission}
