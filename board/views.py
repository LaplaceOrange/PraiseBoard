import csv
import io
import json
import logging
import zipfile

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .auth import clear_login_failures, is_login_locked, record_login_failure
from .forms import AdminLoginForm, RosterUploadForm, SecurePasswordChangeForm, StudentForm
from .models import BoardExport, Classroom, DailyBoard, DailySubmission, PraiseItem, RosterImport, Student, TeacherAssignment
from .permissions import can_access_class, can_manage_class, is_admin, teacher_assignments, visible_classrooms
from .services import (
    board_snapshot, change_board_state, confirm_import, delete_item,
    parse_day, read_roster, reorder_item, save_items,
)

logger = logging.getLogger(__name__)


def _class(user, pk, manage=False):
    if not str(pk).isdigit() or len(str(pk)) > 18:
        raise Http404
    classroom = get_object_or_404(Classroom, pk=pk, is_active=True)
    if not (can_manage_class(user, classroom) if manage else can_access_class(user, classroom)):
        raise PermissionDenied
    return classroom


def _board(user, pk, manage=False):
    board = get_object_or_404(DailyBoard.objects.select_related("classroom"), pk=pk)
    _class(user, board.classroom_id, manage=manage)
    return board


def _error(request, exc):
    messages.error(request, " ".join(exc.messages))


def _context(request, classroom=None):
    if classroom and request.session.get("workspace_classroom_id") != classroom.pk:
        request.session["workspace_classroom_id"] = classroom.pk
    return {
        "classrooms": visible_classrooms(request.user),
        "current_class": classroom,
        "is_admin": is_admin(request.user),
        "today": timezone.localdate(),
    }


def _identities(classroom_id):
    if not str(classroom_id).isdigit() or len(str(classroom_id)) > 18:
        return []
    assignments = TeacherAssignment.objects.filter(
        classroom_id=classroom_id, classroom__is_active=True, is_active=True,
        teacher__is_active=True, teacher__is_superuser=False, subject__is_active=True,
    ).select_related("teacher", "subject")
    seen, identities = set(), []
    for assignment in assignments:
        pair = (assignment.teacher_id, assignment.subject_id)
        if pair in seen:
            continue
        seen.add(pair)
        identities.append({"id": assignment.pk, "label": f"{assignment.subject.name}-{assignment.teacher}"})
    duplicate_labels = {value["label"] for value in identities if sum(
        other["label"] == value["label"] for other in identities
    ) > 1}
    for value in identities:
        if value["label"] in duplicate_labels:
            value["label"] += f"（{next(a.teacher.username for a in assignments if a.pk == value['id'])}）"
    return identities


@require_GET
def identities(request):
    classroom_id = request.GET.get("classroom", "")
    response = JsonResponse({"identities": _identities(classroom_id) if classroom_id.isdigit() else []})
    response["Cache-Control"] = "no-store"
    return response


def teacher_login(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    classroom_id = request.POST.get("classroom") or request.GET.get("classroom", "")
    options = _identities(classroom_id) if str(classroom_id).isdigit() else []
    if request.method == "POST":
        identity_id = request.POST.get("identity", "")
        assignment = TeacherAssignment.objects.filter(
            pk=identity_id if identity_id.isdigit() else 0,
            classroom_id=classroom_id if str(classroom_id).isdigit() else 0,
            is_active=True, teacher__is_active=True, teacher__is_superuser=False,
            classroom__is_active=True, subject__is_active=True,
        ).select_related("teacher").first()
        key = f"teacher:{assignment.teacher_id}" if assignment else "teacher:invalid"
        if is_login_locked(request, key):
            messages.error(request, "登录尝试过多，请在 15 分钟后重试。")
        else:
            user = authenticate(request, username=assignment.teacher.username, password=request.POST.get("password", "")) if assignment else None
            if user:
                clear_login_failures(request, key)
                login(request, user)
                return redirect("dashboard")
            record_login_failure(request, key)
            messages.error(request, "身份或密码不正确，请重新选择并输入密码。")
    return render(request, "board/login.html", {
        "public_classes": Classroom.objects.filter(is_active=True),
        "selected_class": str(classroom_id), "identities": options,
    })


def administrator_login(request):
    if request.user.is_authenticated:
        if not is_admin(request.user):
            raise PermissionDenied
        return redirect("dashboard")
    form = AdminLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        key = f"admin:{form.cleaned_data['username']}"
        if is_login_locked(request, key):
            form.add_error(None, "登录尝试过多，请在 15 分钟后重试。")
        else:
            user = authenticate(request, **form.cleaned_data)
            if user and is_admin(user):
                clear_login_failures(request, key)
                login(request, user)
                return redirect("dashboard")
            record_login_failure(request, key)
            form.add_error(None, "管理员账号或密码不正确。")
    return render(request, "board/admin_login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def password_change(request):
    required = request.user.must_change_password
    form = SecurePasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.must_change_password = False
        user.save(update_fields=("password", "must_change_password"))
        update_session_auth_hash(request, user)
        messages.success(request, "密码已修改。")
        return redirect("dashboard")
    return render(request, "board/password_change.html", {
        **_context(request), "form": form, "required": required,
    })


@login_required
def dashboard(request):
    classrooms = visible_classrooms(request.user)
    selected = request.GET.get("classroom")
    classroom = _class(request.user, selected) if selected else classrooms.first()
    try:
        day = parse_day(request.GET.get("day"))
    except ValidationError as exc:
        _error(request, exc)
        day = timezone.localdate()
    board = None
    manager = False
    assignments = []
    submissions = []
    recent = []
    if classroom:
        manager = can_manage_class(request.user, classroom)
        if not manager:
            day = timezone.localdate()
        board, _ = DailyBoard.objects.get_or_create(classroom=classroom, day=day)
        assignments = list(teacher_assignments(request.user, classroom))
        submissions = list(board.submissions.filter(is_submitted=True).select_related(
            "assignment__teacher", "assignment__subject",
        ).prefetch_related("items")) if manager else list(board.submissions.filter(
            assignment__teacher=request.user,
        ).select_related("assignment__subject").prefetch_related("items"))
        own = {submission.assignment_id: submission for submission in board.submissions.filter(assignment__teacher=request.user)}
        for assignment in assignments:
            assignment.submission = own.get(assignment.pk)
        recent = classroom.boards.filter(revisions__isnull=False).distinct()[:8] if manager else []
    return render(request, "board/dashboard.html", {
        **_context(request, classroom), "day": day, "board": board,
        "manager": manager, "assignments": assignments, "submissions": submissions,
        "recent": recent, "active_nav": "dashboard",
    })


@login_required
def editor(request, board_id, assignment_id):
    board = _board(request.user, board_id)
    assignment = get_object_or_404(TeacherAssignment.objects.select_related("subject", "teacher"), pk=assignment_id, classroom=board.classroom)
    manager = can_manage_class(request.user, board.classroom)
    if board.is_finalized:
        messages.error(request, "榜单已定稿。请先重新打开后再修改。")
        return redirect("board_detail", board_id=board.pk)
    if not manager and (
        assignment.teacher_id != request.user.pk or not assignment.is_active
        or not assignment.subject.is_active or board.day != timezone.localdate()
    ):
        raise PermissionDenied
    submission = DailySubmission.objects.filter(board=board, assignment=assignment).first()
    students = list(board.classroom.students.filter(is_active=True))
    items = [
        {
            "title": item.title, "note": item.note, "all_students": item.all_students,
            "student_ids": [s["id"] for s in item.student_snapshots],
        }
        for item in submission.items.all()
    ] if submission else []
    return render(request, "board/editor.html", {
        **_context(request, board.classroom), "board": board, "assignment": assignment,
        "students_data": [{"id": s.pk, "name": s.name, "student_no": s.student_no} for s in students],
        "initial_items": items, "manager": manager, "active_nav": "dashboard",
    })


@login_required
@require_POST
def submit(request, board_id, assignment_id):
    board = _board(request.user, board_id)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValidationError("填报格式无效。")
        if data.get("mode") not in ("draft", "submit"):
            raise ValidationError("请选择保存草稿或提交。")
        save_items(request.user, board.pk, assignment_id, data.get("items"), data.get("version"), data["mode"] == "submit")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "填报格式无效。"}, status=400)
    except (TeacherAssignment.DoesNotExist, DailyBoard.DoesNotExist):
        raise Http404
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=409)
    return JsonResponse({"redirect": reverse("dashboard") + f"?classroom={board.classroom_id}&day={board.day.isoformat()}"})


@login_required
def board_detail(request, board_id):
    board = _board(request.user, board_id, manage=True)
    snapshot = board.revisions.first().snapshot if board.is_finalized else board_snapshot(board)
    submissions = board.submissions.select_related("assignment__subject", "assignment__teacher").prefetch_related("items")
    return render(request, "board/detail.html", {
        **_context(request, board.classroom), "board": board, "snapshot": snapshot,
        "submissions": submissions, "revisions": board.revisions.prefetch_related("exports"),
        "active_nav": "dashboard",
        "all_assignments": board.classroom.assignments.filter(is_active=True, subject__is_active=True, teacher__is_active=True).select_related("subject", "teacher"),
    })


@login_required
@require_POST
def board_action(request, board_id):
    board = _board(request.user, board_id, manage=True)
    try:
        change_board_state(request.user, board.pk, request.POST.get("action"), request.POST.get("version"),
                           request.POST.get("title", ""), request.POST.get("footer", ""))
        messages.success(request, "榜单状态已更新。" if request.POST.get("action") != "metadata" else "标题和落款已保存。")
    except ValidationError as exc:
        _error(request, exc)
    return redirect("board_detail", board_id=board.pk)


@login_required
@require_POST
def item_action(request, item_id):
    item = get_object_or_404(PraiseItem.objects.select_related("submission__board"), pk=item_id)
    board = _board(request.user, item.submission.board_id, manage=True)
    try:
        action = request.POST.get("action")
        if action == "delete":
            delete_item(request.user, item.pk, request.POST.get("version"))
        else:
            reorder_item(request.user, item.pk, action, request.POST.get("version"))
    except ValidationError as exc:
        _error(request, exc)
    return redirect("board_detail", board_id=board.pk)


@login_required
def preview(request, board_id):
    board = _board(request.user, board_id, manage=True)
    snapshot = board.revisions.first().snapshot if board.is_finalized else board_snapshot(board)
    return render(request, "board/print.html", {"snapshot": snapshot, "screen_preview": True})


@login_required
@require_POST
def export_images(request, board_id):
    board = _board(request.user, board_id, manage=True)
    if not board.is_finalized:
        messages.error(request, "请先定稿，再下载图片。")
        return redirect("board_detail", board_id=board.pk)
    revision = board.revisions.first()
    try:
        from .renderer import ensure_exports
        exports = ensure_exports(revision, request.user)
    except Exception:
        logger.exception("Failed to render board %s", board.pk)
        messages.error(request, "图片生成失败，请稍后重试或联系管理员检查浏览器运行环境。")
        return redirect("board_detail", board_id=board.pk)
    if len(exports) == 1:
        return _image_response(exports[0])
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as files:
        for index, export in enumerate(exports, 1):
            with export.file.open("rb") as image:
                files.writestr(f"praise-{board.day}-{index}.png", image.read())
    archive.seek(0)
    return FileResponse(archive, as_attachment=True, filename=f"praise-{board.day}.zip")


def _image_response(export):
    return FileResponse(export.file.open("rb"), as_attachment=True,
                        filename=f"praise-{export.board.day}-{export.pk}.png", content_type="image/png")


@login_required
def download_export(request, export_id):
    export = get_object_or_404(BoardExport.objects.select_related("board"), pk=export_id)
    _board(request.user, export.board_id, manage=True)
    return _image_response(export)


@login_required
def roster(request, classroom_id):
    classroom = _class(request.user, classroom_id, manage=True)
    editing = request.GET.get("edit")
    student = get_object_or_404(Student, pk=editing, classroom=classroom) if editing else None
    form = StudentForm(request.POST or None, instance=student)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                Classroom.objects.select_for_update().get(pk=classroom.pk)
                instance = form.save(commit=False)
                instance.classroom = classroom
                instance.save()
        except IntegrityError:
            form.add_error("student_no", "本班已经存在该学号。")
        else:
            messages.success(request, "学生名单已保存。")
            return redirect("roster", classroom_id=classroom.pk)
    return render(request, "board/roster.html", {
        **_context(request, classroom), "students": classroom.students.all(), "form": form,
        "editing": student, "active_nav": "roster",
    })


@login_required
@require_POST
def deactivate_student(request, classroom_id, student_id):
    classroom = _class(request.user, classroom_id, manage=True)
    student = get_object_or_404(Student, pk=student_id, classroom=classroom)
    student.is_active = not student.is_active
    student.save(update_fields=("is_active",))
    messages.success(request, "学生在读状态已更新，历史榜单不受影响。")
    return redirect("roster", classroom_id=classroom.pk)


@login_required
def import_roster(request, classroom_id):
    classroom = _class(request.user, classroom_id, manage=True)
    form = RosterUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            rows, errors = read_roster(form.cleaned_data["file"])
        except ValidationError as exc:
            form.add_error("file", exc)
        else:
            preview_import = RosterImport.objects.create(classroom=classroom, created_by=request.user, rows=rows, errors=errors)
            return redirect("import_preview", import_id=preview_import.pk)
    return render(request, "board/import.html", {
        **_context(request, classroom), "form": form, "active_nav": "roster",
    })


@login_required
def import_preview(request, import_id):
    batch = get_object_or_404(RosterImport.objects.select_related("classroom"), pk=import_id)
    _class(request.user, batch.classroom_id, manage=True)
    if not is_admin(request.user) and batch.created_by_id != request.user.pk:
        raise PermissionDenied
    if request.method == "POST":
        try:
            count = confirm_import(request.user, batch.pk)
            messages.success(request, f"已导入 {count} 名学生。相同学号已更新，未出现在文件中的学生保持不变。")
            return redirect("roster", classroom_id=batch.classroom_id)
        except ValidationError as exc:
            _error(request, exc)
    return render(request, "board/import_preview.html", {
        **_context(request, batch.classroom), "batch": batch, "active_nav": "roster",
    })


@login_required
def roster_template(request, classroom_id):
    _class(request.user, classroom_id, manage=True)
    response = HttpResponse("\ufeff", content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="students-template.csv"'
    writer = csv.writer(response)
    writer.writerow(["学号", "姓名"])
    return response


@login_required
def assignments(request, classroom_id):
    classroom = _class(request.user, classroom_id)
    return render(request, "board/assignments.html", {
        **_context(request, classroom),
        "assignments": classroom.assignments.select_related("teacher", "subject"),
        "active_nav": "assignments",
    })


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
