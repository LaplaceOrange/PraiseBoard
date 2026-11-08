from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    BaseScoreRule, Classroom, DailyBoard, ScoreEntry, ScoringDayOverride,
    Student, Subject,
)
from .permissions import can_access_class, can_manage_class, teacher_assignments


CATEGORIES = list(ScoreEntry.Category.choices)[:-1]


def decimal_points(value, nonnegative=False):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) >= Decimal("10000000000"):
            raise ValueError
        if result != result.quantize(Decimal(".01")) or (nonnegative and result < 0):
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("分值须为最多两位小数的有效数字，加分及基础分不能为负数。")


def student_snapshot(student):
    return {
        "id": student.pk, "student_no": student.student_no, "name": student.name,
        "group": student.group, "responsibility": student.responsibility,
    }


def base_score(classroom, day):
    override = classroom.scoring_days.filter(day=day).first()
    enabled = override.enabled if override else day.weekday() < 5
    return configured_base_score(classroom, day) if enabled else Decimal(0)


def configured_base_score(classroom, day):
    rule = classroom.base_score_rules.filter(effective_day__lte=day).first()
    return rule.points if rule else Decimal(5)


def class_subject_names(classroom):
    return list(Subject.objects.filter(
        assignments__classroom=classroom,
    ).distinct().values_list("name", flat=True))


def evaluation_snapshot(board):
    rows = {}
    base = str(base_score(board.classroom, board.day))
    for student in board.classroom.students.filter(is_active=True):
        rows[student.pk] = {
            **student_snapshot(student), "base": base,
            "scores": {key: "0" for key, _ in CATEGORIES}, "subjects": {}, "notes": [],
        }
    details = []
    for entry in board.score_entries.select_related("subject", "created_by"):
        details.append({
            "id": entry.pk, "source": "entry", "category": entry.category,
            "category_label": entry.get_category_display(), "reason": entry.reason,
            "points": str(entry.points), "note": entry.note, "students": entry.student_snapshots,
            "subject": entry.subject.name if entry.subject else "",
            "subject_id": entry.subject_id, "teacher": str(entry.created_by or ""),
        })
    submissions = board.submissions.filter(is_submitted=True).select_related(
        "assignment__subject", "assignment__teacher"
    ).prefetch_related("items")
    for submission in submissions:
        for item in submission.items.all():
            details.append({
                "id": item.pk, "source": "praise", "category": "praise",
                "category_label": "日常表扬", "reason": item.title, "points": str(item.points),
                "note": item.note, "students": item.student_snapshots,
                "subject": submission.assignment.subject.name,
                "subject_id": submission.assignment.subject_id,
                "teacher": str(submission.assignment.teacher),
                "assignment_id": submission.assignment_id,
            })
    for detail in details:
        for student in detail["students"]:
            # Retain recorded students even if they have since left the class.
            row = rows.setdefault(student["id"], {
                **student, "base": "0", "scores": {key: "0" for key, _ in CATEGORIES},
                "subjects": {}, "notes": [],
            })
            category = detail["category"]
            points = Decimal(detail["points"])
            if category != "note":
                row["scores"][category] = str(Decimal(row["scores"][category]) + points)
            if category == "homework" and detail["subject"]:
                subject = detail["subject"]
                row["subjects"][subject] = str(Decimal(row["subjects"].get(subject, "0")) + points)
            text = detail["reason"]
            if detail["note"]:
                text += "：" + detail["note"]
            row["notes"].append(text)
    for row in rows.values():
        row["total"] = str(Decimal(row["base"]) + sum(Decimal(v) for v in row["scores"].values()))
    return {
        "rows": list(rows.values()), "details": details,
        "subjects": class_subject_names(board.classroom),
    }


def daily_snapshot(classroom, day):
    board = DailyBoard.objects.filter(classroom=classroom, day=day).first()
    if board and board.is_finalized:
        revision = board.revisions.first()
        snapshot = dict(revision.snapshot)
        snapshot["revision"] = revision.number
        snapshot["draft"] = False
        # Old revisions have no evaluation. Never reconstruct them from current settings.
        snapshot.setdefault("evaluation", {"rows": [], "details": [], "subjects": [], "legacy": True})
        return snapshot
    if board:
        from .services import board_snapshot
        snapshot = board_snapshot(board)
    else:
        transient = DailyBoard(classroom=classroom, day=day)
        base = str(base_score(classroom, day))
        rows = [{
            **student_snapshot(student), "base": base,
            "scores": {key: "0" for key, _ in CATEGORIES}, "subjects": {}, "notes": [],
            "total": base,
        } for student in classroom.students.filter(is_active=True)]
        snapshot = {
            "classroom": classroom.name, "day": transient.day.isoformat(),
            "title": "今日表扬榜", "footer": "", "sections": [],
            "evaluation": {"rows": rows, "details": [], "subjects": class_subject_names(classroom)},
        }
    return {**snapshot, "revision": None, "draft": True}


def weekly_snapshot(classroom, day):
    start = day - timedelta(days=day.weekday())
    end = min(start + timedelta(days=6), timezone.localdate())
    days = [daily_snapshot(classroom, start + timedelta(days=i)) for i in range((end - start).days + 1)]
    rows, subjects = {}, []
    for snapshot in days:
        evaluation = snapshot["evaluation"]
        for subject in evaluation["subjects"]:
            if subject not in subjects:
                subjects.append(subject)
        for daily in evaluation["rows"]:
            row = rows.setdefault(daily["id"], {
                **{key: daily.get(key, "") for key in ("id", "student_no", "name", "group", "responsibility")},
                "base": "0", "scores": {key: "0" for key, _ in CATEGORIES},
                "subjects": {}, "notes": [], "daily": {},
            })
            row["base"] = str(Decimal(row["base"]) + Decimal(daily["base"]))
            for key, _ in CATEGORIES:
                row["scores"][key] = str(Decimal(row["scores"][key]) + Decimal(daily["scores"][key]))
            row["daily"][snapshot["day"]] = daily
            row["notes"].extend(f'{snapshot["day"]} {note}' for note in daily["notes"])
        if evaluation.get("legacy"):
            # Keep unsupported historical dates explicit instead of treating them as zero.
            snapshot["legacy"] = True
    for row in rows.values():
        row["total"] = str(Decimal(row["base"]) + sum(Decimal(v) for v in row["scores"].values()))
    return {
        "classroom": classroom.name, "day": start.isoformat(), "end": end.isoformat(),
        "title": "班务日志周汇总", "days": days, "rows": list(rows.values()),
        "subjects": subjects, "draft": any(d["draft"] for d in days),
        "legacy": any(d.get("legacy") for d in days),
    }


def assert_entry_access(user, board, entry=None, subject_id=None):
    if can_manage_class(user, board.classroom):
        return
    assignments = teacher_assignments(user, board.classroom)
    try:
        requested_subject_id = int(subject_id) if subject_id else (entry.subject_id if entry else None)
    except (TypeError, ValueError):
        requested_subject_id = None
    if (
        board.day != timezone.localdate() or not can_access_class(user, board.classroom)
        or (entry and (entry.created_by_id != user.pk or entry.category != "homework"))
        or not requested_subject_id or not assignments.filter(subject_id=requested_subject_id).exists()
        or (entry and entry.subject_id != requested_subject_id)
    ):
        raise PermissionDenied


@transaction.atomic
def save_entry(user, board_id, data, version, entry_id=None, delete=False):
    from .services import bump_version, require_version
    board = DailyBoard.objects.select_for_update().select_related("classroom").get(pk=board_id)
    entry = board.score_entries.get(pk=entry_id) if entry_id else None
    assert_entry_access(user, board, entry, data.get("subject_id"))
    require_version(board, version)
    if board.is_finalized:
        raise ValidationError("当天已定稿，请先由班主任重新打开。")
    if delete:
        if not entry:
            raise ValidationError("记录不存在。")
        entry.delete()
        bump_version(board)
        return
    category = data.get("category")
    if category not in ScoreEntry.Category.values:
        raise ValidationError("请选择有效的计分类别。")
    manager = can_manage_class(user, board.classroom)
    if not manager and category != "homework":
        raise PermissionDenied
    points = Decimal(0) if category == "note" else decimal_points(data.get("points", "0"))
    if category == "homework" and points > 0:
        raise ValidationError("作业未交只能登记扣分或零分。")
    reason, note = str(data.get("reason", "")).strip(), str(data.get("note", "")).strip()
    if not reason or len(reason) > 120 or len(note) > 1000:
        raise ValidationError("原因须为 1 至 120 字，备注不能超过 1000 字。")
    subject = None
    if category == "homework":
        subject_query = Subject.objects.filter(
            pk=data.get("subject_id"), is_active=True,
            assignments__classroom=board.classroom, assignments__is_active=True,
        )
        if not manager:
            subject_query = subject_query.filter(assignments__teacher=user)
        subject = subject_query.first()
        if not subject:
            raise ValidationError("请选择本班有效的作业科目。")
    roster = board.classroom.students.filter(is_active=True)
    mode = data.get("target", "students")
    if mode == "group":
        if not data.get("group"):
            raise ValidationError("请选择组号。")
        students = list(roster.filter(group=data["group"]))
    elif mode == "all":
        students = list(roster)
    elif mode == "students":
        try:
            ids = {int(pk) for pk in data.get("student_ids", [])}
        except (ValueError, TypeError):
            raise ValidationError("所选学生无效。")
        students = list(roster.filter(pk__in=ids))
        if len(students) != len(ids):
            raise ValidationError("请选择本班在读学生。")
    else:
        raise ValidationError("请选择有效的对象范围。")
    if not students:
        raise ValidationError("请至少选择一名在读学生。")
    if entry is None:
        entry = ScoreEntry(board=board, created_by=user)
    entry.category, entry.points, entry.reason, entry.note = category, points, reason, note
    entry.subject, entry.updated_by = subject, user
    entry.student_snapshots = [student_snapshot(s) for s in students]
    entry.save()
    bump_version(board)
    return entry


@transaction.atomic
def save_scoring_settings(user, classroom_id, data):
    classroom = Classroom.objects.select_for_update().get(pk=classroom_id)
    if not can_manage_class(user, classroom):
        raise PermissionDenied
    try:
        valid = int(data.get("version")) == classroom.scoring_version
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValidationError("计分设置已更新，请刷新后重试。")
    try:
        day = date.fromisoformat(data.get("day", ""))
    except (TypeError, ValueError):
        raise ValidationError("请输入有效日期。")
    if data.get("action") == "base":
        BaseScoreRule.objects.update_or_create(
            classroom=classroom, effective_day=day,
            defaults={"points": decimal_points(data.get("points"), nonnegative=True), "updated_by": user},
        )
        affected = classroom.boards.filter(day__gte=day)
    elif data.get("action") in ("calendar", "calendar_reset"):
        if DailyBoard.objects.filter(classroom=classroom, day=day, state=DailyBoard.State.FINALIZED).exists():
            raise ValidationError("该日期已定稿，请先重新打开。")
        if data["action"] == "calendar_reset":
            ScoringDayOverride.objects.filter(classroom=classroom, day=day).delete()
        else:
            if data.get("enabled") not in ("0", "1"):
                raise ValidationError("请选择是否发放基础分。")
            note = str(data.get("note", "")).strip()
            if len(note) > 160:
                raise ValidationError("说明不能超过 160 字。")
            ScoringDayOverride.objects.update_or_create(
                classroom=classroom, day=day,
                defaults={"enabled": data.get("enabled") == "1", "note": note, "updated_by": user},
            )
        affected = classroom.boards.filter(day=day)
    else:
        raise ValidationError("无效操作。")
    classroom.scoring_version += 1
    classroom.save(update_fields=("scoring_version",))
    affected.filter(state=DailyBoard.State.OPEN).update(version=F("version") + 1)
