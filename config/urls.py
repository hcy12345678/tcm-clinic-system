from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve as static_serve

BASE_DIR = settings.BASE_DIR
FRONTEND_DIR = BASE_DIR / "frontend"

urlpatterns = [
    # 前后端分离：前端是 frontend/ 下的静态 HTML，只通过 /api/ 取数据
    path("", RedirectView.as_view(url="/app/login.html", permanent=False)),
    path("api/", include("clinic.api_urls")),
    path("app/", RedirectView.as_view(url="/app/login.html", permanent=False)),
    re_path(r"^app/(?P<path>.*)$", static_serve, {"document_root": FRONTEND_DIR}),

    # 旧版服务端渲染页面，保留在 /ssr/ 下作为对照
    path("ssr/", include("clinic.urls")),

    path("django-admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
