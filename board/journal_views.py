import io
import zipfile
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import DailyBoard, ReportBundle, ReportPage, ScoreEntry, Subject
from .permissions import can_manage_class, teacher_assignments
from .reports import REPORT_KINDS, export_workbook, homework_table, prepare_images, report_snapshot
from .scoring import (
    CATEGORIES, assert_entry_access, base_score, configured_base_score,
    daily_snapshot, save_entry, save_scoring_settings, weekly_snapshot,
)
from .services import parse_day
from .views import _class, _context, _error, logger


@login_required
def journal(request, classroom_id):
    classroom = _class(request.user, classroom_id)
    manager = can_manage_class(request.user, classroom)
    try:
        day = parse_day(request.GET.get("day"))
    except ValidationError as exc:
        _error(request, exc)
        day = timezone.localdate()
    if not manager:
        day = timezone.localdate()
    tab = request.GET.get("tab", "daily" if manager else "homework")
    if tab not in ("daily", "entries", "weekly", "homework", "settings", "seating"):
        raise Http404
    if not manager and tab != "homework":
        raise PermissionDenied
    board, _ = DailyBoard.objects.get_or_create(classroom=classroom, day=day)
    calendar_override = classroom.scoring_days.filter(day=day).first()
    form_data = None
    if request.method == "POST":
        form_data = request.POST
        try:
            if request.POST.get("action") in ("base", "calendar", "calendar_reset"):
                save_scoring_settings(request.user, classroom.pk, request.POST)
                messages.success(request, "计分设置已保存，已定稿记录保持原样。")
            elif request.POST.get("action") == "seat_score":
                points = request.POST.get("points")
                if points not in ("-2", "-1", "1", "2"):
                    raise ValidationError("请选择加减 1 分或 2 分。")
                student_id = request.POST.get("student_id", "")
                if not student_id.isdigit():
                    raise ValidationError("请选择有效学生。")
                save_entry(
                    request.user, board.pk, {
                        "category": "discipline", "points": points,
                        "reason": request.POST.get("reason", ""), "note": request.POST.get("note", ""),
                        "target": "students", "student_ids": [student_id],
                    }, request.POST.get("version"),
                )
                messages.success(request, "日常纪律积分已登记。")
            else:
                data = {
                    key: request.POST.get(key, "")
                    for key in ("category", "subject_id", "points", "reason", "note", "target", "group")
                }
                data["student_ids"] = request.POST.getlist("student_ids")
                entry_id = request.POST.get("entry_id")
                if entry_id and (not entry_id.isdigit() or len(entry_id) > 18):
                    raise ValidationError("记录编号无效。")
                save_entry(
                    request.user, board.pk, data, request.POST.get("version"),
                    entry_id=int(entry_id) if entry_id else None, delete=request.POST.get("action") == "delete",
                )
                messages.success(request, "班务记录已保存。")
            return redirect(reverse("journal", args=[classroom.pk]) + f"?day={day}&tab={tab}")
        except (ScoreEntry.DoesNotExist, ValueError, TypeError):
            messages.error(request, "所选记录或科目无效，请刷新后重试。")
        except ValidationError as exc:
            _error(request, exc)
        board.refresh_from_db()
        classroom.refresh_from_db()
    evaluation = daily_snapshot(classroom, day)["evaluation"]
    entries = board.score_entries.select_related("subject", "created_by")
    if not manager:
        entries = entries.filter(created_by=request.user, category="homework", subject__in=(
            teacher_assignments(request.user, classroom).values("subject_id")
        ))
    editing = None
    edit_id = request.GET.get("edit") or (form_data.get("entry_id") if form_data else None)
    if edit_id:
        editing = get_object_or_404(entries, pk=edit_id)
        assert_entry_access(request.user, board, editing)
    initial = {
        "category": "praise" if manager else "homework", "points": "1" if manager else "-1",
        "reason": "", "note": "", "target": "students", "group": "", "subject_id": "",
        "student_ids": [],
    }
    if editing:
        initial.update({
            "category": editing.category, "points": str(editing.points), "reason": editing.reason,
            "note": editing.note, "subject_id": editing.subject_id or "",
            "student_ids": [s["id"] for s in editing.student_snapshots],
        })
    if form_data and form_data.get("action") == "save":
        initial.update({key: form_data.get(key, "") for key in initial if key != "student_ids"})
        initial["student_ids"] = [int(pk) for pk in form_data.getlist("student_ids") if pk.isdigit()]
    subjects = Subject.objects.filter(assignments__classroom=classroom, assignments__is_active=True, is_active=True)
    if not manager:
        subjects = subjects.filter(assignments__teacher=request.user)
    week = weekly_snapshot(classroom, day) if tab in ("weekly", "homework") and manager else None
    if tab == "weekly":
        rows = week["rows"]
    else:
        rows = evaluation["rows"]
    display_rows = [
        {**row, "category_values": [row["scores"][key] for key, _ in CATEGORIES]}
        for row in rows
    ]
    selected_student_id = request.GET.get("student")
    try:
        selected_student_id = int(selected_student_id)
    except (TypeError, ValueError):
        selected_student_id = None
    seat_students = list(classroom.students.filter(is_active=True))
    seat_students.sort(key=lambda student: (
        student.seat_order if student.seat_order else 10**9, student.student_no, student.pk,
    ))
    score_by_student = {row["id"]: row for row in evaluation["rows"]}
    seat_rows = []
    for position, student in enumerate(seat_students, 1):
        score = score_by_student.get(student.pk, {}).get("scores", {}).get("discipline", "0")
        points = Decimal(score)
        amount = abs(points)
        seat_rows.append({
            "student": student, "position": student.seat_order or position, "score": score,
            "tone": "negative" if points < 0 else "positive" if points > 0 else "neutral",
            "intensity": "strong" if amount >= Decimal("2") else "light",
        })
    return render(request, "board/journal.html", {
        **_context(request, classroom), "active_nav": "journal", "manager": manager,
        "board": board, "day": day, "tab": tab, "evaluation": evaluation, "week": week,
        "rows": display_rows, "entries": entries, "editing": editing, "initial": initial,
        "categories": ScoreEntry.Category.choices if manager else [("homework", "作业未交")],
        "students": classroom.students.filter(is_active=True), "subjects": subjects.distinct(),
        "groups": classroom.students.filter(is_active=True).exclude(group="").values_list("group", flat=True).distinct(),
        "base_rules": classroom.base_score_rules.all(), "calendar": classroom.scoring_days.all(),
        "base": base_score(classroom, day), "configured_base": configured_base_score(classroom, day),
        "calendar_override": calendar_override,
        "calendar_enabled": calendar_override.enabled if calendar_override else day.weekday() < 5,
        "homework_tables": [homework_table(week, name) for name in week["subjects"]] if week and tab == "homework" else [],
        "seat_rows": seat_rows, "selected_student_id": selected_student_id,
        "seat_layout": request.GET.get("layout", "seat") if request.GET.get("layout") in ("seat", "number") else "seat",
    })


@login_required
def report(request, classroom_id):
    classroom = _class(request.user, classroom_id, manage=True)
    try:
        day = parse_day(request.GET.get("day"))
        kind = request.GET.get("kind", "evaluation")
        snapshot = report_snapshot(classroom, day, kind, request.GET.get("subject"))
    except ValidationError as exc:
        _error(request, exc)
        return redirect("journal", classroom_id=classroom.pk)
    if request.GET.get("format") == "xlsx":
        return FileResponse(
            export_workbook(snapshot), as_attachment=True,
            filename=f"{kind}-{day}.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return render(request, "board/report.html", {
        **_context(request, classroom), "active_nav": "journal", "day": day, "kind": kind,
        "report_kinds": REPORT_KINDS, "snapshot": snapshot, "subject_id": request.GET.get("subject", ""),
        "subjects": Subject.objects.filter(assignments__classroom=classroom).distinct(),
    })


@login_required
@require_POST
def report_prepare(request, classroom_id):
    classroom = _class(request.user, classroom_id, manage=True)
    try:
        snapshot = report_snapshot(
            classroom, parse_day(request.POST.get("day")),
            request.POST.get("kind", "evaluation"), request.POST.get("subject"),
        )
        bundle = prepare_images(classroom, snapshot, request.user)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    except Exception:
        logger.exception("Failed to prepare report for class %s", classroom.pk)
        return JsonResponse({"error": "图片生成失败，请稍后重试。"}, status=500)
    return JsonResponse({
        "download": reverse("report_download", args=[bundle.pk]),
        "pages": [{
            "number": page.number, "url": reverse("report_page", args=[page.pk]),
        } for page in bundle.pages.all()],
    })


@login_required
def report_page(request, page_id):
    page = get_object_or_404(ReportPage.objects.select_related("bundle"), pk=page_id)
    _class(request.user, page.bundle.classroom_id, manage=True)
    response = FileResponse(page.file.open("rb"), content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    return response


def bundle_download_response(bundle):
    pages = list(bundle.pages.all())
    if len(pages) == 1:
        return FileResponse(pages[0].file.open("rb"), content_type="image/png",
                            as_attachment=True, filename=f"report-{bundle.pk}.png")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for page in pages:
            with page.file.open("rb") as source:
                archive.writestr(f"report-{bundle.pk}-{page.number}.png", source.read())
    output.seek(0)
    return FileResponse(output, as_attachment=True, filename=f"report-{bundle.pk}.zip")


@login_required
def report_download(request, bundle_id):
    bundle = get_object_or_404(ReportBundle, pk=bundle_id)
    _class(request.user, bundle.classroom_id, manage=True)
    return bundle_download_response(bundle)
