from django.shortcuts import redirect
from django.urls import reverse


class ForcedPasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user
            and user.is_authenticated
            and user.must_change_password
            and request.path not in {reverse("password_change_required"), reverse("logout")}
            and not request.path.startswith("/static/")
        ):
            return redirect("password_change_required")
        response = self.get_response(request)
        if user and user.is_authenticated:
            response["Cache-Control"] = "private, no-store"
        return response
