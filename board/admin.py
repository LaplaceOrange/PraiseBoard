from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    BoardExport,
    Classroom,
    DailyBoard,
    DailySubmission,
    LoginFailureBucket,
    PraiseItem,
    RosterImport,
    Student,
    Subject,
    TeacherAssignment,
    User,
)
from .forms import AdminTeacherCreationForm


@admin.register(User)
class BoardUserAdmin(UserAdmin):
    add_form = AdminTeacherCreationForm
    ordering = ("display_name", "username")
    list_display = ("username", "display_name", "is_active", "must_change_password", "password_reset_link")
    list_filter = ("is_active", "must_change_password")
    search_fields = ("username", "display_name", "email")
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "display_name", "email")}),
    )
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("个人信息", {"fields": ("display_name", "email")}),
        ("状态", {"fields": ("is_active", "must_change_password")}),
    )

    @admin.display(description="密码操作")
    def password_reset_link(self, obj):
        url = reverse("admin:board_user_force_password", args=(obj.pk,))
        return format_html('<a href="{}">强制重置密码</a>', url)

    def get_urls(self):
        return [
            path(
                "<path:object_id>/force-password/",
                self.admin_site.admin_view(self.force_password_view),
                name="board_user_force_password",
            )
        ] + super().get_urls()

    def save_model(self, request, obj, form, change):
        if not change:
            obj.set_password("123456")
            obj.must_change_password = True
            obj.is_staff = False
            obj.is_superuser = False
        super().save_model(request, obj, form, change)

    def user_change_password(self, request, id, form_url=""):
        return HttpResponseRedirect(reverse("admin:board_user_force_password", args=(id,)))

    def force_password_view(self, request, object_id):
        user = get_object_or_404(User, pk=object_id)
        if user.is_superuser:
            self.message_user(request, "不能从教师账号列表重置管理员密码。", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:board_user_changelist"))

        error = ""
        if request.method == "POST":
            password = request.POST.get("password", "")
            try:
                if password.isdigit():
                    raise ValidationError("新密码不能全部是数字。")
                if user.check_password(password):
                    raise ValidationError("新密码不能与原密码相同。")
            except ValidationError as exc:
                error = " ".join(exc.messages)
            else:
                user.set_password(password)
                user.must_change_password = False
                user.save(update_fields=("password", "must_change_password"))
                self.message_user(request, f"已重置 {user} 的密码。新密码可直接登录。", level=messages.SUCCESS)
                return HttpResponseRedirect(reverse("admin:board_user_changelist"))

        return render(
            request,
            "admin/board/user/force_password.html",
            {
                **self.admin_site.each_context(request),
                "title": f"强制重置密码：{user}",
                "target_user": user,
                "error": error,
                "opts": self.model._meta,
            },
        )


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("name", "homeroom_teacher", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "homeroom_teacher__display_name")
    autocomplete_fields = ("homeroom_teacher",)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    ordering = ("sort_order", "name")


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ("teacher", "classroom", "subject", "is_active")
    list_filter = ("classroom", "subject", "is_active")
    search_fields = ("teacher__username", "teacher__display_name")
    autocomplete_fields = ("teacher",)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("student_no", "name", "classroom", "is_active")
    list_filter = ("classroom", "is_active")
    search_fields = ("student_no", "name")


@admin.register(DailyBoard)
class DailyBoardAdmin(admin.ModelAdmin):
    list_display = ("classroom", "day", "state", "finalized_by", "finalized_at")
    list_filter = ("state", "classroom")
    date_hierarchy = "day"
    readonly_fields = [field.name for field in DailyBoard._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DailySubmission)
class DailySubmissionAdmin(admin.ModelAdmin):
    list_display = ("board", "assignment", "is_submitted", "submitted_at", "updated_at")
    list_filter = ("is_submitted", "assignment__classroom", "assignment__subject")
    readonly_fields = [field.name for field in DailySubmission._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PraiseItem)
class PraiseItemAdmin(admin.ModelAdmin):
    list_display = ("title", "submission", "all_students", "sort_order")
    list_filter = ("all_students",)
    search_fields = ("title", "note")
    readonly_fields = [field.name for field in PraiseItem._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(BoardExport, ReadOnlyAdmin)
admin.site.register(RosterImport, ReadOnlyAdmin)
admin.site.register(LoginFailureBucket, ReadOnlyAdmin)
