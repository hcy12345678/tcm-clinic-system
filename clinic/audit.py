from .models import OperationLog


def log_action(request, module, action, obj="", detail=""):
    ip = request.META.get("REMOTE_ADDR")
    OperationLog.objects.create(
        operator=request.user if request.user.is_authenticated else None,
        module=module,
        action=action,
        object_id=str(obj)[:100],
        detail=detail[:300],
        ip_address=ip,
    )
