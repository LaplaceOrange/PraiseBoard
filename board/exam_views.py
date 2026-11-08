from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from .exam_radar import SUBJECTS, TOTAL_FULL_SCORE, overall_grade, radar_chart, read_exam_scores, total_score
from .forms import ExamRadarUploadForm
from .models import ExamReport, ExamScore
from .views import _class, _context


@login_required
def exam_radar(request, classroom_id):
    classroom = _class(request.user, classroom_id, manage=True)
    upload_form = ExamRadarUploadForm()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "upload":
            upload_form = ExamRadarUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                try:
                    scores, sheet_title = read_exam_scores(
                        upload_form.cleaned_data["file"],
                        classroom,
                        upload_form.cleaned_data["sheet_name"].strip(),
                    )
                except ValidationError as exc:
                    upload_form.add_error("file", " ".join(exc.messages))
                else:
                    title = upload_form.cleaned_data["title"].strip() or sheet_title
                    with transaction.atomic():
                        exam = ExamReport.objects.create(
                            classroom=classroom, title=title, imported_by=request.user,
                        )
                        ExamScore.objects.bulk_create([
                            ExamScore(exam=exam, **score) for score in scores
                        ])
                    messages.success(request, f"已导入“{title}”，共 {sum(not row['is_reference'] for row in scores)} 名学生。")
                    first = exam.scores.filter(is_reference=False).first()
                    url = reverse("exam_radar", args=[classroom.pk]) + f"?exam={exam.pk}"
                    if first:
                        url += f"&student={first.pk}"
                    return redirect(url)

    exams = ExamReport.objects.filter(classroom=classroom)
    exam_id = request.GET.get("exam")
    if exam_id and (not exam_id.isdigit() or len(exam_id) > 18):
        raise Http404
    selected_exam = get_object_or_404(exams, pk=exam_id) if exam_id else exams.first()
    records = list(selected_exam.scores.filter(is_reference=False).select_related("student")) if selected_exam else []
    selected_record = None
    if records:
        requested_student = request.GET.get("student", "")
        selected_record = next(
            (record for record in records if str(record.pk) == requested_student),
            None,
        )
        if requested_student and not selected_record:
            raise Http404
        selected_record = selected_record or records[0]
    chart = radar_chart(selected_record) if selected_record else None
    for record in records:
        record.total = total_score(record)
        record.grade = overall_grade(record)
    return render(request, "board/radar.html", {
        **_context(request, classroom),
        "active_nav": "radar",
        "exams": exams,
        "selected_exam": selected_exam,
        "records": records,
        "selected_record": selected_record,
        "chart": chart,
        "subjects": SUBJECTS,
        "total_full_score": TOTAL_FULL_SCORE,
        "upload_form": upload_form,
    })


@login_required
def exam_radar_download(request, classroom_id, exam_id, score_id):
    classroom = _class(request.user, classroom_id, manage=True)
    exam = get_object_or_404(ExamReport.objects.select_related("classroom"), pk=exam_id, classroom=classroom)
    record = get_object_or_404(
        ExamScore.objects.select_related("exam").filter(exam=exam, is_reference=False),
        pk=score_id,
    )
    response = HttpResponse(
        render_to_string("board/radar_svg.html", {
            "exam": exam,
            "record": record,
            "chart": radar_chart(record),
        }),
        content_type="image/svg+xml; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="radar-{record.pk}.svg"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def exam_radar_delete(request, classroom_id, exam_id):
    classroom = _class(request.user, classroom_id, manage=True)
    exam = get_object_or_404(ExamReport, pk=exam_id, classroom=classroom)
    exam.delete()
    messages.success(request, "考试成绩已删除。")
    return redirect("exam_radar", classroom_id=classroom.pk)
