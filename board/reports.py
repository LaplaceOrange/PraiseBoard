import hashlib
import io
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import ReportBundle, ReportPage
from .scoring import CATEGORIES, daily_snapshot, weekly_snapshot


REPORT_KINDS = (
    ("evaluation", "每日评价表"), ("weekly", "班务日志周汇总"),
    ("homework", "各科作业登记表"), ("praise", "表扬榜"),
)


def evaluation_table(evaluation, title):
    headers = ["学号", "组号", "负责", "姓名", "基础分"] + [label for _, label in CATEGORIES] + ["合计", "备注"]
    rows = [[
        row["student_no"], row.get("group", ""), row.get("responsibility", ""), row["name"],
        row["base"], *[row["scores"][key] for key, _ in CATEGORIES], row["total"], "\n".join(row["notes"]),
    ] for row in evaluation["rows"]]
    return {
        "title": title, "headers": headers, "rows": rows, "numeric": list(range(4, 11)),
        "legacy": evaluation.get("legacy", False),
    }


def homework_table(week, subject):
    headers = ["学号", "组号", "负责", "姓名"] + [d["day"][5:] for d in week["days"]] + ["合计", "备注"]
    rows = []
    for student in week["rows"]:
        values, notes = [], []
        for day in week["days"]:
            daily = student["daily"].get(day["day"])
            values.append(daily["subjects"].get(subject, "0") if daily else None)
            for detail in day["evaluation"]["details"]:
                if detail["category"] == "homework" and detail["subject"] == subject and any(
                    s["id"] == student["id"] for s in detail["students"]
                ):
                    notes.append(f'{day["day"]} {detail["reason"]}' + (f'：{detail["note"]}' if detail["note"] else ""))
        rows.append([
            student["student_no"], student.get("group", ""), student.get("responsibility", ""), student["name"],
            *values, str(sum(Decimal(value) for value in values if value is not None)), "\n".join(notes),
        ])
    return {
        "title": f"{subject}作业登记表", "headers": headers, "rows": rows,
        "numeric": list(range(4, len(headers) - 1)), "legacy": week["legacy"],
    }


def report_snapshot(classroom, day, kind, subject_id=None):
    if kind not in dict(REPORT_KINDS):
        raise ValidationError("无效的报告类型。")
    if kind in ("weekly", "homework"):
        week = weekly_snapshot(classroom, day)
        dates = f'{week["day"]} 至 {week["end"]}'
        sources = [{"day": d["day"], "revision": d["revision"], "draft": d["draft"]} for d in week["days"]]
        if kind == "weekly":
            tables = [evaluation_table(week, "周汇总")]
            tables += [evaluation_table(d["evaluation"], d["day"]) for d in week["days"]]
            tables += [homework_table(week, subject) for subject in week["subjects"]]
        else:
            subjects = dict(classroom.assignments.values_list("subject_id", "subject__name"))
            try:
                subject_id = int(subject_id)
            except (ValueError, TypeError):
                subject_id = next(iter(subjects), None)
            if subject_id not in subjects:
                raise ValidationError("请选择本班科目。")
            tables = [homework_table(week, subjects[subject_id])]
        return {
            "classroom": classroom.name, "title": dict(REPORT_KINDS)[kind], "dates": dates,
            "draft": week["draft"], "sources": sources, "tables": tables, "kind": kind,
            "legacy": week["legacy"],
        }
    snapshot = daily_snapshot(classroom, day)
    if kind == "praise":
        if snapshot["draft"]:
            snapshot["title"] += "（草稿）"
        return {
            "classroom": classroom.name, "title": "表扬榜", "dates": day.isoformat(),
            "draft": snapshot["draft"], "sources": [{"day": snapshot["day"], "revision": snapshot["revision"], "draft": snapshot["draft"]}],
            "praise": snapshot, "tables": [], "kind": kind,
        }
    return {
        "classroom": classroom.name, "title": "每日综合评价表", "dates": day.isoformat(),
        "draft": snapshot["draft"], "sources": [{"day": snapshot["day"], "revision": snapshot["revision"], "draft": snapshot["draft"]}],
        "tables": [evaluation_table(snapshot["evaluation"], day.isoformat())], "kind": kind,
        "legacy": snapshot["evaluation"].get("legacy", False),
    }


def export_workbook(snapshot):
    workbook = Workbook()
    workbook.remove(workbook.active)
    tables = list(snapshot["tables"])
    if snapshot["kind"] == "praise":
        tables = [{
            "title": "表扬榜", "headers": ["科目", "教师", "学生", "表扬项目", "每人加分", "备注"],
            "numeric": [4],
            "rows": [[section["subject"], item.get("teacher", ""),
                      "、".join(s["name"] for s in item["students"]) if not item["all_students"] else "全班同学",
                      item["title"], item.get("points", "0"), item.get("note", "")]
                     for section in snapshot["praise"]["sections"] for item in section["items"]],
        }]
    versions = "；".join(
        f'{source["day"]} ' + ("草稿" if source["draft"] else f'第{source["revision"]}版')
        for source in snapshot["sources"]
    )
    for index, table in enumerate(tables):
        name = table["title"]
        for character in "[]:*?/\\":
            name = name.replace(character, "-")
        name = name[:28]
        if name in workbook.sheetnames:
            name = f"{name[:25]}-{index}"
        sheet = workbook.create_sheet(name)
        sheet.sheet_view.showGridLines = False
        title = f'{snapshot["classroom"]} {table["title"]}' + ("（草稿）" if snapshot["draft"] else "")
        sheet.append([title])
        sheet.append([versions])
        sheet.append(["旧版定稿未保存积分，相关日期未计入汇总。" if table.get("legacy") else snapshot["dates"]])
        sheet.append(table["headers"])
        for row in table["rows"]:
            sheet.append([Decimal(value) if i in table["numeric"] and value is not None else value
                          for i, value in enumerate(row)])
        for row in sheet:
            for cell in row:
                # User text must remain literal, including strings beginning with '='.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.font = Font(name="Microsoft YaHei", size=11, color="18353B")
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if cell.row >= 5 and cell.column - 1 in table["numeric"]:
                    cell.number_format = "0.##"
        sheet["A1"].font = Font(name="Microsoft YaHei", size=16, bold=True, color="18353B")
        sheet.row_dimensions[1].height = 30
        sheet.row_dimensions[2].height = 36
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(table["headers"]))
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(table["headers"]))
        sheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(table["headers"]))
        for cell in sheet[4]:
            cell.fill = PatternFill("solid", fgColor="147C78")
            cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF", size=11)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.freeze_panes = "E5"
        sheet.auto_filter.ref = f'A4:{get_column_letter(len(table["headers"]))}{max(sheet.max_row, 4)}'
        sheet.print_title_rows = "1:4"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
        sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
        for column, label in enumerate(table["headers"], 1):
            sheet.column_dimensions[get_column_letter(column)].width = 48 if label == "备注" else (16 if label in ("姓名", "学生", "表扬项目") else 12)
        for number, row in enumerate(table["rows"], 5):
            lines = max((len(str(value or "")) + 44) // 45 + str(value or "").count("\n") for value in row)
            sheet.row_dimensions[number].height = min(400, max(26, lines * 17))
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


@transaction.atomic
def prepare_images(classroom, snapshot, user):
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    fingerprint = hashlib.sha256(encoded).hexdigest()
    bundle, _ = ReportBundle.objects.get_or_create(
        classroom=classroom, kind=snapshot["kind"], fingerprint=fingerprint,
        defaults={"snapshot": snapshot, "created_by": user},
    )
    bundle = ReportBundle.objects.select_for_update().get(pk=bundle.pk)
    if bundle.pages.exists():
        return bundle
    from .renderer import render_pages
    images = render_pages(snapshot.get("praise", snapshot), template=(
        "board/print.html" if snapshot["kind"] == "praise" else "board/report_print.html"
    ))
    created = []
    try:
        for index, image in enumerate(images, 1):
            page = ReportPage(bundle=bundle, number=index)
            page.file.save(f"report-{bundle.pk}-{index}.png", ContentFile(image), save=False)
            created.append(page)
            page.save()
    except Exception:
        for page in created:
            page.file.delete(save=False)
        raise
    return bundle
