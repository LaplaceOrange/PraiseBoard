import math
import re
import textwrap
import zipfile
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from openpyxl import load_workbook

from .models import Student


SUBJECTS = (
    ("chinese", "语文", 120),
    ("mathematics", "数学", 120),
    ("english", "英语", 120),
    ("physics", "物理", 100),
    ("morals", "道法", 100),
    ("history", "历史", 100),
    ("pe", "体育", 60),
)
TOTAL_FULL_SCORE = sum(full_score for _, _, full_score in SUBJECTS)
REFERENCE_STUDENTS = {
    "60": ("及格线 C", "#d35f4b"),
    "75": ("普高线 B", "#d19a2a"),
    "85": ("前五所 A", "#2877a8"),
    "92": ("一中线 S", "#2f7d52"),
}
GRADE_THRESHOLDS = (
    (Decimal("0.92"), "S"),
    (Decimal("0.85"), "A"),
    (Decimal("0.75"), "B"),
    (Decimal("0.60"), "C"),
)


def _identifier(value):
    if value is None or isinstance(value, bool):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if len(text) > 40:
        raise ValidationError("学号不能超过 40 个字符。")
    try:
        numeric = Decimal(text)
    except InvalidOperation:
        return text
    if numeric.is_finite() and abs(numeric) < Decimal("1e40") and numeric == numeric.to_integral_value():
        return str(int(numeric))
    return text


def _header(value):
    return re.sub(r"\s+", "", str(value or "")).replace("（", "(").replace("）", ")")


def _score(value, subject, full_score, row_number):
    try:
        score = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValidationError(f"第 {row_number} 行的{subject}成绩无效。")
    if not score.is_finite() or score < 0 or score > full_score:
        raise ValidationError(f"第 {row_number} 行的{subject}成绩须在 0 至 {full_score} 分之间，最多两位小数。")
    try:
        if score != score.quantize(Decimal(".01")):
            raise ValidationError(f"第 {row_number} 行的{subject}成绩须在 0 至 {full_score} 分之间，最多两位小数。")
    except InvalidOperation as exc:
        raise ValidationError(f"第 {row_number} 行的{subject}成绩无效。") from exc
    return score


def read_exam_scores(uploaded_file, classroom, sheet_name=""):
    if uploaded_file.size > 10 * 1024 * 1024:
        raise ValidationError("成绩文件不能超过 10 MB。")
    if not uploaded_file.name.lower().endswith(".xlsx"):
        raise ValidationError("请上传 XLSX 格式的成绩文件。")
    workbook = None
    try:
        uploaded_file.seek(0)
        with zipfile.ZipFile(uploaded_file) as archive:
            if sum(info.file_size for info in archive.infolist()) > 30 * 1024 * 1024:
                raise ValidationError("成绩文件解压后过大，请精简后上传。")
        uploaded_file.seek(0)
        workbook = load_workbook(uploaded_file, read_only=True, data_only=True)
        if sheet_name:
            if sheet_name not in workbook.sheetnames:
                raise ValidationError("工作表名称不存在，请检查后重试。")
            worksheet = workbook[sheet_name]
        else:
            worksheet = workbook[workbook.sheetnames[0]]
        if (worksheet.max_row or 0) > 2000 or (worksheet.max_column or 0) > 100:
            raise ValidationError("成绩表范围过大，请确认只包含本次考试成绩。")
        rows = worksheet.iter_rows(values_only=True)
        headers = next(rows, None)
        if not headers:
            raise ValidationError("成绩表为空。")
        header_indexes = {}
        for index, value in enumerate(headers):
            normalized = _header(value)
            if normalized:
                if normalized in header_indexes:
                    raise ValidationError(f"成绩表存在重复列：{normalized}。")
                header_indexes[normalized] = index
        student_no_index = header_indexes.get("学号")
        name_index = header_indexes.get("姓名")
        if student_no_index is None or name_index is None:
            raise ValidationError("成绩表须包含“学号”和“姓名”列。")
        subject_indexes = {}
        for field, subject, full_score in SUBJECTS:
            index = header_indexes.get(f"{subject}({full_score})")
            if index is None:
                index = header_indexes.get(subject)
            if index is None:
                raise ValidationError(f"成绩表缺少“{subject}({full_score})”列。")
            subject_indexes[field] = index

        roster = {}
        for student in Student.objects.filter(classroom=classroom):
            key = _identifier(student.student_no)
            if key in roster:
                raise ValidationError("本班名单含有仅前导零不同的学号，请核对后再导入。")
            roster[key] = student
        parsed, identifiers, found_references, unknown_students = [], set(), set(), []
        for row_number, values in enumerate(rows, start=2):
            if row_number > 2000 or len(values) > 100:
                raise ValidationError("成绩表范围过大，请确认只包含本次考试成绩。")
            if not values or all(value is None or str(value).strip() == "" for value in values):
                continue
            student_no = _identifier(values[student_no_index] if student_no_index < len(values) else None)
            student_name = str(values[name_index] or "").strip() if name_index < len(values) else ""
            if not student_no:
                raise ValidationError(f"第 {row_number} 行缺少学号。")
            if student_no in identifiers:
                raise ValidationError(f"学号 {student_no} 重复，请检查成绩表。")
            identifiers.add(student_no)
            is_reference = student_no in REFERENCE_STUDENTS
            student = None if is_reference else roster.get(student_no)
            if not is_reference and not student:
                unknown_students.append(student_no)
            if not is_reference and not student_name:
                raise ValidationError(f"第 {row_number} 行缺少姓名。")
            if len(student_name) > 80:
                raise ValidationError(f"第 {row_number} 行的姓名不能超过 80 个字符。")
            if student and student_name != student.name:
                raise ValidationError(f"第 {row_number} 行的姓名与本班学号 {student.student_no} 不一致，请核对。")
            scores = {
                field: _score(
                    values[index] if index < len(values) else None,
                    subject,
                    full_score,
                    row_number,
                )
                for field, subject, full_score in SUBJECTS
                for index in [subject_indexes[field]]
            }
            if is_reference:
                found_references.add(student_no)
                student_name = student_name or REFERENCE_STUDENTS[student_no][0]
            elif student:
                student_no = student.student_no
            parsed.append({
                "student": student,
                "student_no": student_no,
                "student_name": student_name,
                "is_reference": is_reference,
                **scores,
            })
        if unknown_students:
            examples = "、".join(unknown_students[:5])
            raise ValidationError(f"以下学号不在本班名单中：{examples}。请先核对名单或成绩文件。")
        missing_references = set(REFERENCE_STUDENTS) - found_references
        if missing_references:
            labels = "、".join(REFERENCE_STUDENTS[number][0] for number in sorted(missing_references))
            raise ValidationError(f"成绩表缺少参考线数据：{labels}。")
        if not any(not row["is_reference"] for row in parsed):
            raise ValidationError("成绩表没有可绘制的学生成绩。")
        return parsed, worksheet.title
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("无法读取成绩文件，请确认文件未损坏且格式为 XLSX。") from exc
    finally:
        if workbook is not None:
            workbook.close()


def total_score(record):
    return sum((Decimal(getattr(record, field)) for field, _, _ in SUBJECTS), Decimal(0))


def overall_grade(record):
    percentage = total_score(record) / Decimal(TOTAL_FULL_SCORE)
    for threshold, grade in GRADE_THRESHOLDS:
        if percentage >= threshold:
            return grade
    return "D"


def _point(radius, index, count=7, center=(280, 260)):
    angle = index * 2 * math.pi / count
    x = center[0] + math.sin(angle) * radius
    y = center[1] - math.cos(angle) * radius
    return x, y


def _points_string(points):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def radar_chart(record):
    title_lines = [
        line for value in (
            record.exam.classroom.name,
            record.exam.title,
            f"{record.student_no} · {record.student_name} 学科能力雷达图",
        ) for line in textwrap.wrap(value, width=25)
    ]
    header_height = 36 + len(title_lines) * 28
    center = (340, header_height + 220)
    radius = 145
    axes, student_values = [], []
    for index, (field, subject, full_score) in enumerate(SUBJECTS):
        score = Decimal(getattr(record, field))
        percentage = round(round(score) / full_score * 100)
        point = _point(radius * percentage / 100, index, center=center)
        label = _point(radius + 52, index, center=center)
        axes.append({
            "name": subject, "full_score": full_score,
            "x1": center[0], "y1": center[1], "x2": _point(radius, index, center=center)[0],
            "y2": _point(radius, index, center=center)[1],
            "label_x": label[0], "label_y": label[1],
            "anchor": "start" if label[0] > center[0] + 12 else (
                "end" if label[0] < center[0] - 12 else "middle"
            ),
            "score_x": label[0], "score_y": label[1] + 19,
            "score": format(score, "f").rstrip("0").rstrip(".") if score % 1 else str(int(score)),
            "percentage": percentage,
            "point_x": point[0], "point_y": point[1],
        })
        student_values.append(point)

    reference_rows = {
        row.student_no: row
        for row in record.exam.scores.filter(is_reference=True)
    }
    references = []
    for number, (label, color) in REFERENCE_STUDENTS.items():
        reference = reference_rows[number]
        points = []
        for index, (field, _, full_score) in enumerate(SUBJECTS):
            value = Decimal(getattr(reference, field))
            percent = round(value / Decimal(full_score) * 100)
            x, y = _point(radius * percent / 100, index, center=center)
            points.append((x, y))
        references.append({
            "number": number, "label": label, "color": color,
            "points": _points_string(points),
            "legend_x": 70 if len(references) % 2 == 0 else 380,
            "legend_y": header_height + 455 + (len(references) // 2) * 26,
        })

    return {
        "title_lines": [{"text": line, "y": 34 + index * 28} for index, line in enumerate(title_lines)],
        "header_height": header_height,
        "image_height": header_height + 525,
        "footer_y": header_height + 513,
        "axes": axes,
        "rings": [
            {"label": f"{percentage}%", "points": _points_string([
                _point(radius * percentage / 100, index, center=center)
                for index in range(len(SUBJECTS))
            ])}
            for percentage in (20, 40, 60, 80, 100)
        ],
        "ring_labels": [
            {
                "label": f"{percentage}%",
                "x": center[0] + 5,
                "y": center[1] - radius * percentage / 100 - 2,
            }
            for percentage in (20, 40, 60, 80, 100)
        ],
        "references": references,
        "student_polygon": _points_string(student_values),
        "center_x": center[0], "center_y": center[1],
        "total": total_score(record),
        "percentage": round(total_score(record) / Decimal(TOTAL_FULL_SCORE) * 100),
        "grade": overall_grade(record),
    }
