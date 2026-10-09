from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.shortcuts import redirect
from django.utils import timezone


class BoardAdminConfig(AdminConfig):
    default_site = "board.admin_site.BoardAdminSite"


class BoardAdminSite(AdminSite):
    site_url = "/dashboard/"
    enable_nav_sidebar = False

    def each_context(self, request):
        # AdminConfig imports this module before Django's models are ready.
        from .permissions import visible_classrooms

        context = super().each_context(request)
        classroom = None
        if context["has_permission"]:
            classrooms = visible_classrooms(request.user)
            selected = request.session.get("workspace_classroom_id")
            if isinstance(selected, int) and 0 < selected < 2**63:
                classroom = classrooms.filter(pk=selected).first()
            if classroom is None:
                classroom = classrooms.first()
            if classroom:
                if selected != classroom.pk:
                    request.session["workspace_classroom_id"] = classroom.pk
            else:
                request.session.pop("workspace_classroom_id", None)
        return {
            **context,
            "current_class": classroom,
            "is_admin": request.user.is_superuser,
            "active_nav": "admin",
            "workspace_context": "全站管理",
            "today": timezone.localdate(),
        }

    def has_permission(self, request):
        return (
            request.user.is_active and request.user.is_superuser
            and not request.user.must_change_password
        )

    def login(self, request, extra_context=None):
        return redirect("administrator_login")
