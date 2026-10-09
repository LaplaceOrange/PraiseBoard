import io
import json
import tempfile
from datetime import timedelta

from django.contrib.auth import SESSION_KEY
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from .models import (
    BoardRevision, Classroom, DailyBoard, DailySubmission, PraiseItem,
    RosterImport, Student, Subject, TeacherAssignment, User,
)
from .services import change_board_state, confirm_import, read_roster, save_items


@override_settings(DEBUG=True, STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                                     "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class BoardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin", password="Initial-admin-9876", display_name="管理员")
        cls.home = User.objects.create_user("home", password="Teacher-home-9876", display_name="张老师")
        cls.teacher = User.objects.create_user("teacher", password="Teacher-other-9876", display_name="李老师")
        cls.other = User.objects.create_user("other", password="Teacher-outside-9876", display_name="王老师")
        cls.classroom = Classroom.objects.create(name="测试一班", homeroom_teacher=cls.home)
        cls.second = Classroom.objects.create(name="测试二班", homeroom_teacher=cls.other)
        cls.subject = Subject.objects.create(name="数学")
        cls.assignment = TeacherAssignment.objects.create(teacher=cls.teacher, classroom=cls.classroom, subject=cls.subject)
        cls.home_assignment = TeacherAssignment.objects.create(teacher=cls.home, classroom=cls.classroom, subject=cls.subject)
        cls.other_assignment = TeacherAssignment.objects.create(teacher=cls.other, classroom=cls.second, subject=cls.subject)
        cls.student = Student.objects.create(classroom=cls.classroom, student_no="001", name="同名学生")
        cls.student2 = Student.objects.create(classroom=cls.classroom, student_no="002", name="同名学生")
        cls.foreign_student = Student.objects.create(classroom=cls.second, student_no="001", name="其他班学生")
        cls.board = DailyBoard.objects.create(classroom=cls.classroom, day=timezone.localdate())

    def items(self, all_students=False):
        return [{"title": "课堂积极", "note": "认真思考", "all_students": all_students,
                 "student_ids": [self.student.pk]}]

    def setUp(self):
        self.board.day = timezone.localdate()
        self.board.save(update_fields=("day",))

    def test_admin_navigation_keeps_selected_class_across_backend_pages(self):
        self.client.force_login(self.admin)
        self.client.get(reverse("dashboard"), {"classroom": self.second.pk})
        self.assertEqual(self.client.session["workspace_classroom_id"], self.second.pk)
        for url in (
            reverse("admin:index"),
            reverse("admin:board_user_changelist"),
            reverse("admin:board_classroom_change", args=[self.classroom.pk]),
            reverse("admin:board_user_force_password", args=[self.teacher.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["current_class"], self.second)
                self.assertContains(response, f'href="{reverse("roster", args=[self.second.pk])}"')
                self.assertContains(response, f'href="{reverse("assignments", args=[self.second.pk])}"')
                self.assertContains(response, f'href="{reverse("dashboard")}?classroom={self.second.pk}"')

    def test_admin_navigation_handles_missing_and_inactive_classrooms(self):
        self.client.force_login(self.admin)
        for selected in (None, "invalid", 10**100, -1, self.second.pk):
            session = self.client.session
            session["workspace_classroom_id"] = selected
            session.save()
            if selected == self.second.pk:
                self.second.is_active = False
                self.second.save(update_fields=["is_active"])
            response = self.client.get(reverse("admin:index"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["current_class"], self.classroom)
            self.assertEqual(self.client.session["workspace_classroom_id"], self.classroom.pk)
        Classroom.objects.update(is_active=False)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["current_class"])
        self.assertNotIn("workspace_classroom_id", self.client.session)
        self.assertNotContains(response, 'href="/classes/')

    def test_navigation_memory_does_not_grant_class_or_admin_access(self):
        self.client.force_login(self.teacher)
        self.client.get(reverse("dashboard"), {"classroom": self.classroom.pk})
        self.assertEqual(self.client.session["workspace_classroom_id"], self.classroom.pk)
        response = self.client.get(reverse("dashboard"), {"classroom": self.second.pk})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.session["workspace_classroom_id"], self.classroom.pk)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

    def submit(self, user=None, items=None):
        return save_items(user or self.teacher, self.board.pk, self.assignment.pk,
                          items or self.items(), 0)

    def test_initial_password_forces_change_and_cannot_bypass(self):
        self.teacher.set_password("123456")
        self.teacher.must_change_password = True
        self.teacher.save()
        response = self.client.post(reverse("login"), {
            "classroom": self.classroom.pk, "identity": self.assignment.pk, "password": "123456"
        })
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        for url in (reverse("dashboard"), reverse("roster", args=[self.classroom.pk]),
                    reverse("submit", args=[self.board.pk, self.assignment.pk]), "/staff-room/"):
            response = self.client.get(url)
            self.assertRedirects(response, reverse("password_change_required"), fetch_redirect_response=False)
        response = self.client.post(reverse("password_change_required"), {
            "old_password": "123456", "new_password1": "Distinct-new-pass-8715",
            "new_password2": "Distinct-new-pass-8715",
        })
        self.assertRedirects(response, reverse("dashboard"))
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.must_change_password)
        self.assertTrue(self.teacher.check_password("Distinct-new-pass-8715"))

    def test_teacher_identity_is_scoped_and_admin_hidden(self):
        response = self.client.get(reverse("identities"), {"classroom": self.classroom.pk})
        values = response.json()["identities"]
        self.assertEqual({entry["label"] for entry in values}, {"数学-张老师", "数学-李老师"})
        self.assertEqual(self.client.get(reverse("identities"), {"classroom": "bad"}).json()["identities"], [])
        response = self.client.post(reverse("login"), {
            "classroom": self.classroom.pk, "identity": self.other_assignment.pk, "password": "Teacher-outside-9876",
        })
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(response.status_code, 200)

    def test_same_teacher_multiple_subjects_same_account(self):
        subject = Subject.objects.create(name="科学")
        second = TeacherAssignment.objects.create(teacher=self.teacher, classroom=self.classroom, subject=subject)
        response = self.client.post(reverse("login"), {
            "classroom": self.classroom.pk, "identity": second.pk, "password": "Teacher-other-9876",
        })
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.teacher.pk)
        self.assertEqual(response.status_code, 302)

    def test_login_attempt_limit(self):
        for _ in range(6):
            response = self.client.post(reverse("login"), {
                "classroom": self.classroom.pk, "identity": self.assignment.pk, "password": "wrong",
            })
        self.assertContains(response, "登录尝试过多")
        response = self.client.post(reverse("login"), {
            "classroom": self.classroom.pk, "identity": self.assignment.pk, "password": "Teacher-other-9876",
        })
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(response.status_code, 200)
        self.assertIn("数学-张老师", self.client.get(reverse("login"), {"classroom": self.classroom.pk}).content.decode())

    def test_only_admin_can_reset_password_and_reset_invalidates_session(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("admin:board_user_changelist")).status_code, 302)
        old_session = self.client.session.session_key
        from django.test import Client
        admin_client = Client()
        admin_client.force_login(self.admin)
        response = admin_client.post(reverse("admin:board_user_force_password", args=[self.teacher.pk]),
                                     {"password": "Reset-teacher-pass"})
        self.assertEqual(response.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password("Reset-teacher-pass"))
        self.assertFalse(self.teacher.must_change_password)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        response = self.client.post(reverse("login"), {
            "classroom": self.classroom.pk, "identity": self.assignment.pk, "password": "Reset-teacher-pass",
        })
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertNotEqual(self.client.session.session_key, old_session)

    def test_password_policy_allows_short_non_numeric_and_rejects_same_or_numeric(self):
        self.client.force_login(self.teacher)
        url = reverse("password_change")
        response = self.client.post(url, {
            "old_password": "Teacher-other-9876",
            "new_password1": "abc",
            "new_password2": "abc",
        })
        self.assertRedirects(response, reverse("dashboard"))
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password("abc"))

        self.client.force_login(self.teacher)
        response = self.client.post(url, {
            "old_password": "abc",
            "new_password1": "abc",
            "new_password2": "abc",
        })
        self.assertContains(response, "新密码不能与原密码相同")

        response = self.client.post(url, {
            "old_password": "abc",
            "new_password1": "123456",
            "new_password2": "123456",
        })
        self.assertContains(response, "新密码不能全部是数字")

    def test_admin_creation_uses_default_password(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin:board_user_add"), {
            "username": "new-teacher", "display_name": "新老师", "email": "",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="new-teacher")
        self.assertTrue(user.check_password("123456"))
        self.assertTrue(user.must_change_password)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_cross_class_and_roster_boundaries(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("roster", args=[self.classroom.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboard"), {"classroom": self.second.pk}).status_code, 403)
        with self.assertRaises(ValidationError):
            self.submit(items=[{"title": "项目", "student_ids": [self.foreign_student.pk]}])
        self.assertFalse(PraiseItem.objects.exists())

    def test_subject_ownership_and_assignment_revocation(self):
        with self.assertRaises(PermissionDenied):
            self.submit(user=self.other)
        self.assignment.is_active = False
        self.assignment.save()
        with self.assertRaises(PermissionDenied):
            self.submit()

    def test_multiple_items_single_multi_and_whole_class(self):
        items = self.items() + [
            {"title": "作业优秀", "student_ids": [self.student.pk, self.student2.pk]},
            {"title": "共同进步", "all_students": True, "student_ids": []},
        ]
        submission = self.submit(items=items)
        self.assertTrue(submission.is_submitted)
        self.assertEqual(submission.items.count(), 3)
        self.assertEqual(len(submission.items.last().student_snapshots), 2)

    def test_draft_not_in_snapshot(self):
        save_items(self.teacher, self.board.pk, self.assignment.pk, self.items(), 0, submitted=False)
        from .services import board_snapshot
        self.assertFalse(board_snapshot(self.board)["sections"])

    def test_past_date_only_manager_can_edit(self):
        self.board.day -= timedelta(days=1)
        self.board.save()
        with self.assertRaises(PermissionDenied):
            self.submit()
        submission = self.submit(user=self.home)
        self.assertTrue(submission.is_submitted)

    def test_finalize_lock_reopen_and_preserved_snapshot(self):
        self.submit()
        change_board_state(self.home, self.board.pk, "finalize", 1, "进步值得看见", "班主任")
        self.board.refresh_from_db()
        revision = self.board.revisions.first()
        self.assertTrue(self.board.is_finalized)
        self.student.name = "更改姓名"
        self.student.save()
        self.assertEqual(revision.snapshot["sections"][0]["items"][0]["students"][0]["name"], "同名学生")
        with self.assertRaises(ValidationError):
            save_items(self.teacher, self.board.pk, self.assignment.pk, self.items(), 2)
        change_board_state(self.home, self.board.pk, "reopen", 2)
        save_items(self.teacher, self.board.pk, self.assignment.pk, self.items(True), 3)
        change_board_state(self.home, self.board.pk, "finalize", 4)
        self.assertEqual(BoardRevision.objects.filter(board=self.board).count(), 2)
        revision.refresh_from_db()
        self.assertEqual(revision.snapshot["title"], "进步值得看见")

    def test_stale_version_and_empty_finalize_rejected(self):
        with self.assertRaises(ValidationError):
            change_board_state(self.home, self.board.pk, "finalize", 0)
        self.submit()
        with self.assertRaises(ValidationError):
            self.submit()
        self.assertEqual(PraiseItem.objects.count(), 1)

    def test_csv_preview_duplicate_and_confirm_atomic(self):
        upload = SimpleUploadedFile("students.csv", "学号,姓名\n003,同名学生\n004,同名学生\n".encode("utf-8-sig"))
        rows, errors = read_roster(upload)
        self.assertFalse(errors)
        batch = RosterImport.objects.create(classroom=self.classroom, created_by=self.home, rows=rows)
        self.assertEqual(confirm_import(self.home, batch.pk), 2)
        self.assertEqual(Student.objects.filter(classroom=self.classroom).count(), 4)
        with self.assertRaises(ValidationError):
            confirm_import(self.home, batch.pk)
        duplicate = SimpleUploadedFile("students.csv", "学号,姓名\n005,甲\n005,乙\n".encode())
        rows, errors = read_roster(duplicate)
        batch = RosterImport.objects.create(classroom=self.classroom, created_by=self.home, rows=rows, errors=errors)
        with self.assertRaises(ValidationError):
            confirm_import(self.home, batch.pk)
        self.assertFalse(Student.objects.filter(student_no="005").exists())

    def test_xlsx_import_and_invalid_headers(self):
        workbook = Workbook()
        workbook.active.append(["学号", "姓名"])
        workbook.active.append(["0005", "测试学生"])
        stream = io.BytesIO()
        workbook.save(stream)
        rows, errors = read_roster(SimpleUploadedFile("students.xlsx", stream.getvalue()))
        self.assertEqual(rows, [{"student_no": "0005", "name": "测试学生"}])
        self.assertFalse(errors)
        with self.assertRaises(ValidationError):
            read_roster(SimpleUploadedFile("students.csv", "名字\n甲\n".encode()))

    def test_manager_can_import_not_outsider(self):
        batch = RosterImport.objects.create(classroom=self.classroom, created_by=self.home,
                                            rows=[{"student_no": "009", "name": "新学生"}])
        with self.assertRaises(PermissionDenied):
            confirm_import(self.teacher, batch.pk)

    def test_manager_pages_render_and_teacher_export_denied(self):
        self.submit()
        self.client.force_login(self.home)
        for url in [
            reverse("dashboard"), reverse("board_detail", args=[self.board.pk]),
            reverse("editor", args=[self.board.pk, self.assignment.pk]),
            reverse("roster", args=[self.classroom.pk]), reverse("import_roster", args=[self.classroom.pk]),
            reverse("assignments", args=[self.classroom.pk]), reverse("preview", args=[self.board.pk]),
            reverse("password_change"),
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(reverse("export", args=[self.board.pk])).status_code, 403)

    def test_write_api_validation_and_csrf(self):
        self.client.force_login(self.teacher)
        url = reverse("submit", args=[self.board.pk, self.assignment.pk])
        response = self.client.post(url, json.dumps({"items": self.items(), "mode": "submit", "version": 0}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)
        response = self.client.post(url, json.dumps({"items": self.items(), "mode": "submit", "version": 0}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 409)
        response = self.client.post(url, "[]", content_type="application/json")
        self.assertEqual(response.status_code, 409)
        from django.test import Client
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.force_login(self.teacher)
        self.assertEqual(strict_client.post(url, "{}", content_type="application/json").status_code, 403)

    def test_export_cache_and_historical_download_permissions(self):
        self.submit()
        change_board_state(self.home, self.board.pk, "finalize", 1)
        from .renderer import ensure_exports
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            with patch("board.renderer.render_pages", return_value=[b"\x89PNG-test"]) as render:
                first = ensure_exports(self.board.revisions.first(), self.home)
                second = ensure_exports(self.board.revisions.first(), self.home)
                self.assertEqual(first[0].pk, second[0].pk)
                self.assertEqual(render.call_count, 1)
            self.client.force_login(self.home)
            response = self.client.get(reverse("download_export", args=[first[0].pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "private, no-store")
            response.close()
            self.client.force_login(self.teacher)
            self.assertEqual(self.client.get(reverse("download_export", args=[first[0].pk])).status_code, 403)


@override_settings(DEBUG=True, STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                                     "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class RendererTests(TestCase):
    def test_names_are_headings_and_annotations_stay_with_each_page(self):
        from django.template.loader import render_to_string
        from playwright.sync_api import sync_playwright
        snapshot = {
            "classroom": "演示班级", "day": timezone.localdate().isoformat(),
            "title": "今日表扬榜", "footer": "",
            "sections": [{"subject": "数学", "items": [{
                "title": "认真思考", "note": "每一份努力都值得肯定",
                "teacher": "演示老师", "all_students": False,
                "students": [{"name": f"示例同学{i:03d}"} for i in range(240)],
            }, {
                "title": "共同进步", "note": "", "teacher": "演示老师",
                "all_students": True, "students": [],
            }]}],
        }
        html = render_to_string("board/print.html", {"snapshot": snapshot})
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1080, "height": 1440})
                page.route("**/*", lambda route: route.abort())
                page.set_content(html)
                page.wait_for_function("window.boardReady === true")
                names = page.locator(".print-name").all_text_contents()
                self.assertEqual(names, [f"示例同学{i:03d}" for i in range(240)] + ["全班同学"])
                self.assertGreater(page.locator(".print-page").count(), 1)
                self.assertTrue(page.evaluate("""() => [...document.querySelectorAll('.print-item')].every(
                    item => item.firstElementChild.tagName === 'H3' &&
                    item.querySelector('.print-name') &&
                    item.querySelector('.print-attribution').textContent === '科目：数学 · 教师：演示老师'
                )"""))
                self.assertFalse(page.evaluate("""() => [...document.querySelectorAll('.print-content')].some(
                    element => element.scrollHeight > element.clientHeight + 1 ||
                    element.scrollWidth > element.clientWidth + 1
                )"""))
            finally:
                browser.close()

    def test_multiline_notes_paginate_below_repeated_student_heading(self):
        from django.template.loader import render_to_string
        from playwright.sync_api import sync_playwright
        note = "\n".join(f"认真完成第{i}项练习。" for i in range(30))
        self.assertLessEqual(len(note), 400)
        snapshot = {
            "classroom": "演示班级", "day": timezone.localdate().isoformat(),
            "title": "今日表扬榜", "footer": "",
            "sections": [{"subject": "语文", "items": [{
                "title": "坚持练习", "note": note, "teacher": "演示老师",
                "all_students": False, "students": [{"name": "示例同学"}],
            }]}],
        }
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1080, "height": 1440})
                page.set_content(render_to_string("board/print.html", {"snapshot": snapshot}))
                page.wait_for_function("window.boardReady === true")
                parts = page.locator(".print-note").all_text_contents()
                self.assertGreater(len(parts), 1)
                self.assertEqual("".join(part.removeprefix("原因与备注：") for part in parts), note)
                self.assertTrue(all(name == "示例同学" for name in page.locator(".print-item-title").all_text_contents()))
                self.assertFalse(page.evaluate("""() => [...document.querySelectorAll('.print-content')].some(
                    element => element.scrollHeight > element.clientHeight + 1
                )"""))
            finally:
                browser.close()

    def test_chinese_long_list_paginates_without_external_assets(self):
        from .renderer import render_pages
        snapshot = {
            "classroom": "中文测试班", "day": timezone.localdate().isoformat(),
            "title": "今日表扬榜", "footer": "继续努力",
            "sections": [
                {"subject": "数学", "items": [{
                    "title": "认真思考", "note": "每一份努力都值得肯定", "all_students": False,
                    "students": [{"name": f"测试同学{i:03d}"} for i in range(240)],
                }]},
                {"subject": "语文", "items": [{"title": "积极参与", "note": "", "all_students": True, "students": []}]},
            ],
        }
        images = render_pages(snapshot)
        self.assertGreater(len(images), 1)
        self.assertLess(len(images), 12)
        for image in images:
            self.assertTrue(image.startswith(b"\x89PNG"))
            self.assertGreater(len(image), 10000)
