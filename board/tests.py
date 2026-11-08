import io
import json
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import SESSION_KEY
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from .models import (
    BaseScoreRule, BoardRevision, Classroom, DailyBoard, DailySubmission, ExamReport, ExamScore, PraiseItem,
    ReportBundle, ReportPage, RosterImport, ScoringDayOverride, ScoreEntry,
    Student, Subject, TeacherAssignment, User,
)
from .services import change_board_state, confirm_import, read_roster, save_items
from .scoring import base_score, daily_snapshot, save_entry, save_scoring_settings, weekly_snapshot


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

    def test_admin_index_localizes_exam_model_names(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "考试报告")
        self.assertContains(response, "考试成绩")
        self.assertContains(response, "模型名称")
        self.assertContains(response, "添加链接")
        self.assertContains(response, "修改或查看列表链接")
        self.assertContains(response, "修改")
        self.assertNotContains(response, "Exam reports")
        self.assertNotContains(response, "Exam scores")
        self.assertNotContains(response, "Model name")
        self.assertNotContains(response, "Add link")
        self.assertNotContains(response, "Change or view list link")

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

    def test_authentication_pages_are_not_cacheable(self):
        for url in (reverse("login"), reverse("administrator_login")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertIn("private", response["Cache-Control"])

        self.client.force_login(self.home)
        response = self.client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])

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

    def test_base_only_day_can_be_finalized(self):
        change_board_state(self.home, self.board.pk, "finalize", 0)
        self.board.refresh_from_db()
        self.assertTrue(self.board.is_finalized)
        revision = self.board.revisions.first()
        self.assertFalse(revision.snapshot["sections"])
        self.assertEqual(len(revision.snapshot["evaluation"]["rows"]), 2)

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

    def test_stale_version_rejected(self):
        with self.assertRaises(ValidationError):
            change_board_state(self.home, self.board.pk, "finalize", -1)
        self.submit()
        with self.assertRaises(ValidationError):
            self.submit()
        self.assertEqual(PraiseItem.objects.count(), 1)

    def test_praise_points_default_and_submitted_praise_scores_once(self):
        self.assertEqual(PraiseItem._meta.get_field("points").default, 1)
        self.submit()
        item = PraiseItem.objects.get()
        self.assertEqual(item.points, Decimal("1"))
        self.assertEqual(
            Decimal(daily_snapshot(self.classroom, self.board.day)["evaluation"]["rows"][0]["scores"]["praise"]),
            Decimal("1"),
        )

        self.board.refresh_from_db()
        save_items(self.teacher, self.board.pk, self.assignment.pk, [{
            "id": item.pk, "title": item.title, "note": item.note, "points": "2.5",
            "student_ids": [self.student.pk],
        }], self.board.version)
        score = daily_snapshot(self.classroom, self.board.day)["evaluation"]["rows"][0]["scores"]["praise"]
        self.assertEqual(Decimal(score), Decimal("2.5"))
        self.assertEqual(PraiseItem.objects.count(), 1)
        self.board.refresh_from_db()
        save_items(self.teacher, self.board.pk, self.assignment.pk, [{
            "id": item.pk, "title": item.title, "note": item.note, "points": "0",
            "student_ids": [self.student.pk],
        }], self.board.version)
        score = daily_snapshot(self.classroom, self.board.day)["evaluation"]["rows"][0]["scores"]["praise"]
        self.assertEqual(Decimal(score), Decimal("0"))

    def test_base_score_effective_dates_and_calendar_exceptions(self):
        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        saturday = monday + timedelta(days=5)
        sunday = monday + timedelta(days=6)
        BaseScoreRule.objects.create(classroom=self.classroom, effective_day=monday + timedelta(days=3),
                                     points=Decimal("2.5"), updated_by=self.home)
        ScoringDayOverride.objects.create(classroom=self.classroom, day=monday + timedelta(days=4),
                                          enabled=False, updated_by=self.home)
        ScoringDayOverride.objects.create(classroom=self.classroom, day=saturday, enabled=True, updated_by=self.home)

        self.assertEqual(base_score(self.classroom, monday + timedelta(days=2)), Decimal("5"))
        self.assertEqual(base_score(self.classroom, monday + timedelta(days=3)), Decimal("2.5"))
        self.assertEqual(base_score(self.classroom, monday + timedelta(days=4)), Decimal("0"))
        self.assertEqual(base_score(self.classroom, saturday), Decimal("2.5"))
        self.assertEqual(base_score(self.classroom, sunday), Decimal("0"))

    def test_scoring_settings_validate_manager_and_detect_stale_versions(self):
        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        payload = {"action": "base", "version": 0, "day": monday.isoformat(), "points": "4.5"}
        with self.assertRaises(PermissionDenied):
            save_scoring_settings(self.teacher, self.classroom.pk, payload)
        save_scoring_settings(self.home, self.classroom.pk, payload)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.scoring_version, 1)
        self.assertEqual(base_score(self.classroom, monday), Decimal("4.5"))
        with self.assertRaises(ValidationError):
            save_scoring_settings(self.home, self.classroom.pk, payload)

        saturday = monday + timedelta(days=5)
        calendar_payload = {
            "action": "calendar", "version": 1, "day": saturday.isoformat(),
            "enabled": "1", "note": "周末补课",
        }
        save_scoring_settings(self.home, self.classroom.pk, calendar_payload)
        self.classroom.refresh_from_db()
        self.assertEqual(base_score(self.classroom, saturday), Decimal("4.5"))
        calendar_payload.update(action="calendar_reset", version=self.classroom.scoring_version)
        save_scoring_settings(self.home, self.classroom.pk, calendar_payload)
        self.classroom.refresh_from_db()
        self.assertEqual(base_score(self.classroom, saturday), Decimal("0"))

    def test_entries_edit_delete_notes_and_weekly_decimal_totals(self):
        day = self.board.day
        entry = save_entry(self.home, self.board.pk, {
            "category": "discipline", "points": "2.5", "reason": "值日认真",
            "note": "主动完成", "target": "students", "student_ids": [str(self.student.pk)],
        }, self.board.version)
        self.board.refresh_from_db()
        homework = save_entry(self.home, self.board.pk, {
            "category": "homework", "subject_id": str(self.subject.pk), "points": "-0.5",
            "reason": "未交练习", "target": "students", "student_ids": [str(self.student.pk)],
        }, self.board.version)
        self.board.refresh_from_db()
        note = save_entry(self.home, self.board.pk, {
            "category": "note", "points": "", "reason": "家校联系",
            "note": "已告知家长", "target": "students", "student_ids": [str(self.student.pk)],
        }, self.board.version)
        self.board.refresh_from_db()

        evaluation = daily_snapshot(self.classroom, day)["evaluation"]
        student_row = next(row for row in evaluation["rows"] if row["id"] == self.student.pk)
        self.assertEqual(Decimal(student_row["scores"]["discipline"]), Decimal("2.5"))
        self.assertEqual(Decimal(student_row["scores"]["homework"]), Decimal("-0.5"))
        self.assertEqual(Decimal(student_row["total"]), Decimal(student_row["base"]) + Decimal("2.0"))
        self.assertIn("家校联系：已告知家长", student_row["notes"])

        self.student.group = "二组"
        self.student.save(update_fields=("group",))
        self.student2.group = "二组"
        self.student2.save(update_fields=("group",))
        self.board.refresh_from_db()
        grouped = save_entry(self.home, self.board.pk, {
            "category": "arrival", "points": "0.5", "reason": "早到",
            "note": "", "target": "group", "group": "二组",
        }, self.board.version)
        self.assertEqual(len(grouped.student_snapshots), 2)
        self.assertEqual({student["group"] for student in grouped.student_snapshots}, {"二组"})

        edit = save_entry(self.home, self.board.pk, {
            "category": "discipline", "points": "1.5", "reason": "值日复核",
            "note": "", "target": "students", "student_ids": [str(self.student.pk)],
        }, self.board.version + 1, entry_id=entry.pk)
        self.assertEqual(edit.pk, entry.pk)
        self.board.refresh_from_db()
        save_entry(self.home, self.board.pk, {}, self.board.version, entry_id=homework.pk, delete=True)

        weekly = weekly_snapshot(self.classroom, day)
        row = next(row for row in weekly["rows"] if row["id"] == self.student.pk)
        expected_base = Decimal("5") * sum(
            1 for offset in range((day.weekday() + 1)) if (day - timedelta(days=offset)).weekday() < 5
        )
        self.assertEqual(Decimal(row["base"]), expected_base)
        self.assertEqual(Decimal(row["scores"]["discipline"]), Decimal("1.5"))
        self.assertEqual(Decimal(row["scores"]["homework"]), Decimal("0"))
        self.assertEqual(Decimal(row["scores"]["arrival"]), Decimal("0.5"))
        self.assertEqual(Decimal(row["total"]), expected_base + Decimal("2.0"))
        self.assertEqual(ScoreEntry.objects.count(), 3)
        self.assertEqual(note.points, Decimal("0"))

    def test_seating_journal_scores_individual_students_and_reuses_report_rows(self):
        from .reports import report_snapshot

        self.student.seat_order = 2
        self.student.save(update_fields=("seat_order",))
        self.student2.seat_order = 1
        self.student2.save(update_fields=("seat_order",))
        self.client.force_login(self.home)
        url = reverse("journal", args=[self.classroom.pk])
        response = self.client.get(url, {"day": self.board.day, "tab": "seating", "layout": "seat"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "按座位排")
        self.assertContains(response, "座位 1")
        self.assertContains(response, "学号 002")
        self.assertContains(response, "同名学生")

        response = self.client.get(url, {"day": self.board.day, "tab": "seating", "layout": "number"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "001")
        self.assertNotContains(response, "座位 1")

        payload = {
            "action": "seat_score", "version": self.board.version, "student_id": self.student.pk,
            "reason": "课堂发言积极", "note": "主动回答问题", "points": "2",
        }
        response = self.client.post(url + f"?day={self.board.day}&tab=seating", payload)
        self.assertRedirects(response, f"{url}?day={self.board.day}&tab=seating")
        entry = ScoreEntry.objects.get(board=self.board, category="discipline")
        self.assertEqual(entry.points, Decimal("2"))
        self.assertEqual(entry.reason, "课堂发言积极")
        self.assertEqual(entry.student_snapshots[0]["student_no"], "001")

        snapshot = report_snapshot(self.classroom, self.board.day, "evaluation")
        table = snapshot["tables"][0]
        row = next(row for row in table["rows"] if row[0] == "001")
        self.assertEqual(table["headers"][:4], ["学号", "组号", "负责", "姓名"])
        self.assertEqual(row[8], "2.00")

        self.board.refresh_from_db()
        change_board_state(self.home, self.board.pk, "finalize", self.board.version)
        self.board.refresh_from_db()
        response = self.client.post(url + f"?day={self.board.day}&tab=seating", {
            **payload, "version": self.board.version,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ScoreEntry.objects.filter(board=self.board).count(), 1)

    def test_finalized_scoring_snapshot_survives_roster_and_setting_changes(self):
        ScoringDayOverride.objects.create(
            classroom=self.classroom, day=self.board.day, enabled=True, updated_by=self.home,
        )
        BaseScoreRule.objects.create(
            classroom=self.classroom, effective_day=self.board.day,
            points=Decimal("3.5"), updated_by=self.home,
        )
        entry = save_entry(self.home, self.board.pk, {
            "category": "health", "points": "0.5", "reason": "体育表现好",
            "note": "", "target": "students", "student_ids": [str(self.student.pk)],
        }, self.board.version)
        self.board.refresh_from_db()
        change_board_state(self.home, self.board.pk, "finalize", self.board.version)
        revision = self.board.revisions.first()
        original = next(row for row in revision.snapshot["evaluation"]["rows"] if row["id"] == self.student.pk)
        self.assertEqual(Decimal(original["base"]), Decimal("3.5"))
        self.assertEqual(Decimal(original["scores"]["health"]), Decimal("0.5"))
        self.assertEqual(original["name"], "同名学生")

        self.student.name = "新姓名"
        self.student.group = "星星组"
        self.student.save()
        BaseScoreRule.objects.filter(classroom=self.classroom, effective_day=self.board.day).update(points="9.5")
        saved = daily_snapshot(self.classroom, self.board.day)
        saved_row = next(row for row in saved["evaluation"]["rows"] if row["id"] == self.student.pk)
        self.assertEqual(saved_row, original)
        self.assertEqual(revision.snapshot["evaluation"]["details"][0]["id"], entry.pk)

        self.board.refresh_from_db()
        change_board_state(self.home, self.board.pk, "reopen", self.board.version)
        self.assertEqual(revision.snapshot["evaluation"]["rows"][0]["name"], "同名学生")

    def test_weekly_xlsx_has_summary_daily_and_empty_subject_sheets(self):
        from .reports import homework_table, report_snapshot

        empty_week = self.board.day - timedelta(days=14)
        empty_week -= timedelta(days=empty_week.weekday())
        snapshot = report_snapshot(self.classroom, empty_week, "weekly")
        self.assertIn("数学作业登记表", [table["title"] for table in snapshot["tables"]])
        self.assertEqual(len(snapshot["sources"]), 7)
        self.assertEqual(len(homework_table(weekly_snapshot(self.classroom, empty_week), "数学")["rows"]), 2)

        self.client.force_login(self.home)
        response = self.client.get(reverse("report", args=[self.classroom.pk]), {
            "day": self.board.day.isoformat(), "kind": "weekly", "format": "xlsx",
        })
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(io.BytesIO(b"".join(response.streaming_content)), data_only=True)
        self.assertIn("周汇总", workbook.sheetnames)
        self.assertIn("数学作业登记表", workbook.sheetnames)
        summary = workbook["周汇总"]
        self.assertEqual(summary.cell(row=5, column=11).value, 25)
        self.assertEqual(summary.cell(row=5, column=12).value, None)
        response.close()

    def test_report_image_generation_and_access_control(self):
        from unittest.mock import patch

        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("report", args=[self.classroom.pk])).status_code, 403)

        self.client.force_login(self.home)
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            with patch("board.renderer.render_pages", return_value=[b"\x89PNG-test"]):
                response = self.client.post(reverse("report_prepare", args=[self.classroom.pk]), {
                    "day": self.board.day.isoformat(), "kind": "evaluation",
                })
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(len(payload["pages"]), 1)
                page = ReportPage.objects.get()
                self.assertEqual(page.bundle.kind, "evaluation")
                self.assertTrue(ReportBundle.objects.filter(pk=page.bundle_id).exists())
                image = self.client.get(payload["pages"][0]["url"])
                self.assertEqual(image.status_code, 200)
                self.assertEqual(image["Content-Type"], "image/png")
                self.assertEqual(image["Cache-Control"], "private, no-store")
                download = self.client.get(payload["download"])
                self.assertEqual(download.status_code, 200)
                self.assertEqual(download["Content-Type"], "image/png")
                download.close()
                image.close()
                response.close()
            page.file.delete(save=False)

    def test_subject_teacher_cannot_move_homework_record_to_unassigned_subject(self):
        language = Subject.objects.create(name="语文")
        TeacherAssignment.objects.create(teacher=self.home, classroom=self.classroom, subject=language)
        entry = ScoreEntry.objects.create(
            board=self.board, category=ScoreEntry.Category.HOMEWORK, subject=language,
            reason="未完成", points=Decimal("-1"), created_by=self.teacher,
            student_snapshots=[{"id": self.student.pk, "student_no": self.student.student_no, "name": self.student.name}],
        )
        data = {
            "category": "homework", "subject_id": str(self.subject.pk), "points": "-2",
            "reason": "改科目", "target": "students", "student_ids": [str(self.student.pk)],
        }
        with self.assertRaises(PermissionDenied):
            save_entry(self.teacher, self.board.pk, data, self.board.version, entry_id=entry.pk)
        entry.refresh_from_db()
        self.assertEqual(entry.subject_id, language.pk)
        self.assertEqual(entry.points, Decimal("-1"))

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
        workbook.active.append(["学号", "姓名", "组号", "负责"])
        workbook.active.append(["0005", "测试学生", "二组", "值日"])
        stream = io.BytesIO()
        workbook.save(stream)
        rows, errors = read_roster(SimpleUploadedFile("students.xlsx", stream.getvalue()))
        self.assertEqual(rows, [{
            "student_no": "0005", "name": "测试学生", "group": "二组", "responsibility": "值日",
        }])
        self.assertFalse(errors)
        with self.assertRaises(ValidationError):
            read_roster(SimpleUploadedFile("students.csv", "名字\n甲\n".encode()))

    def make_exam_workbook(self, rows=None):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "期末成绩"
        sheet.append(["学号", "姓名", "语文(120)", "数学(120)", "英语(120)",
                      "物理(100)", "道法(100)", "历史(100)", "体育(60)"])
        rows = rows or [
            ["001", "同名学生", 120, 120, 120, 100, 100, 100, 60],
            ["002", "同名学生", 90, 90, 90, 75, 75, 75, 45],
            ["60", "及格参考", 72, 72, 72, 60, 60, 60, 36],
            ["75", "普高参考", 90, 90, 90, 75, 75, 75, 45],
            ["85", "前五所参考", 102, 102, 102, 85, 85, 85, 51],
            ["92", "一中参考", 110.4, 110.4, 110.4, 92, 92, 92, 55.2],
        ]
        for row in rows:
            sheet.append(row)
        stream = io.BytesIO()
        workbook.save(stream)
        return SimpleUploadedFile("exam.xlsx", stream.getvalue())

    def test_exam_radar_upload_draws_class_roster_and_reference_lines(self):
        self.client.force_login(self.home)
        response = self.client.post(reverse("exam_radar", args=[self.classroom.pk]), {
            "action": "upload",
            "title": "期末考试",
            "sheet_name": "",
            "file": self.make_exam_workbook(),
        })
        exam = ExamReport.objects.get(classroom=self.classroom)
        self.assertRedirects(
            response,
            f'{reverse("exam_radar", args=[self.classroom.pk])}?exam={exam.pk}&student={exam.scores.filter(is_reference=False).first().pk}',
            fetch_redirect_response=False,
        )
        self.assertEqual(exam.title, "期末考试")
        self.assertEqual(exam.scores.filter(is_reference=True).count(), 4)
        self.assertEqual(exam.scores.filter(is_reference=False).count(), 2)
        self.assertEqual(exam.scores.filter(is_reference=False).first().student, self.student)

        from .exam_radar import TOTAL_FULL_SCORE, overall_grade, radar_chart, total_score
        self.assertEqual(TOTAL_FULL_SCORE, 720)
        top_score = exam.scores.get(student_no="001")
        middle_score = exam.scores.get(student_no="002")
        self.assertEqual(total_score(top_score), Decimal("720"))
        self.assertEqual(overall_grade(top_score), "S")
        self.assertEqual(total_score(middle_score), Decimal("540"))
        self.assertEqual(overall_grade(middle_score), "B")
        chart = radar_chart(top_score)
        self.assertEqual(len(chart["axes"]), 7)
        self.assertEqual(len(chart["references"]), 4)
        self.assertEqual(chart["axes"][0]["percentage"], 100)

        page = self.client.get(reverse("exam_radar", args=[self.classroom.pk]), {"exam": exam.pk})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "期末考试")
        self.assertContains(page, "720")
        self.assertNotContains(page, "及格参考")
        svg = self.client.get(reverse(
            "exam_radar_download",
            args=[self.classroom.pk, exam.pk, top_score.pk],
        ))
        self.assertEqual(svg.status_code, 200)
        self.assertEqual(svg["Content-Type"], "image/svg+xml; charset=utf-8")
        self.assertIn("<polygon", svg.content.decode())

    def test_exam_radar_grade_thresholds_use_all_seven_subjects(self):
        from .exam_radar import overall_grade

        full_scores = (120, 120, 120, 100, 100, 100, 60)
        cases = []
        for percentage, expected, below in [
            (Decimal("0.92"), "S", "A"),
            (Decimal("0.85"), "A", "B"),
            (Decimal("0.75"), "B", "C"),
            (Decimal("0.60"), "C", "D"),
        ]:
            exact = [Decimal(full) * percentage for full in full_scores]
            cases.extend([
                (tuple(exact), expected),
                (tuple([exact[0] - Decimal(".01"), *exact[1:]]), below),
            ])
        cases = [
            *cases,
            ((72, 72, 72, 60, 60, Decimal("59.99"), 36), "D"),
        ]
        for scores, expected in cases:
            with self.subTest(expected=expected):
                record = ExamScore(**dict(zip(
                    ("chinese", "mathematics", "english", "physics", "morals", "history", "pe"),
                    scores,
                )))
                self.assertEqual(overall_grade(record), expected)

    def test_exam_radar_import_rejects_unknown_students_missing_reference_and_bad_scores(self):
        from .exam_radar import read_exam_scores

        upload = self.make_exam_workbook(rows=[
            ["001", "同名学生", 120, 120, 120, 100, 100, 100, 60],
            ["003", "名单外学生", 90, 90, 90, 75, 75, 75, 45],
            ["60", "及格参考", 72, 72, 72, 60, 60, 60, 36],
            ["75", "普高参考", 90, 90, 90, 75, 75, 75, 45],
            ["85", "前五所参考", 102, 102, 102, 85, 85, 85, 51],
            ["92", "一中参考", 110, 110, 110, 92, 92, 92, 55],
        ])
        with self.assertRaisesMessage(ValidationError, "不在本班名单中"):
            read_exam_scores(upload, self.classroom)

        upload = self.make_exam_workbook(rows=[
            ["001", "同名学生", 121, 120, 120, 100, 100, 100, 60],
            ["60", "及格参考", 72, 72, 72, 60, 60, 60, 36],
            ["75", "普高参考", 90, 90, 90, 75, 75, 75, 45],
            ["85", "前五所参考", 102, 102, 102, 85, 85, 85, 51],
            ["92", "一中参考", 110, 110, 110, 92, 92, 92, 55],
        ])
        with self.assertRaisesMessage(ValidationError, "语文成绩须在 0 至 120 分之间"):
            read_exam_scores(upload, self.classroom)

        upload = self.make_exam_workbook(rows=[
            ["001", "同名学生", 120, 120, 120, 100, 100, 100, 60],
            ["60", "及格参考", 72, 72, 72, 60, 60, 60, 36],
            ["75", "普高参考", 90, 90, 90, 75, 75, 75, 45],
            ["85", "前五所参考", 102, 102, 102, 85, 85, 85, 51],
        ])
        with self.assertRaisesMessage(ValidationError, "缺少参考线数据"):
            read_exam_scores(upload, self.classroom)
        self.assertFalse(ExamReport.objects.exists())

    def test_exam_radar_is_restricted_to_class_managers(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("exam_radar", args=[self.classroom.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("exam_radar", args=[self.classroom.pk]), {}).status_code, 403)

        exam = ExamReport.objects.create(classroom=self.classroom, title="范围检查")
        score = ExamScore.objects.create(
            exam=exam, student=self.student, student_no=self.student.student_no,
            student_name=self.student.name, chinese=100, mathematics=100, english=100,
            physics=80, morals=80, history=80, pe=40,
        )
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse(
            "exam_radar_download", args=[self.classroom.pk, exam.pk, score.pk],
        )).status_code, 403)
        self.client.force_login(self.home)
        self.assertEqual(self.client.get(reverse(
            "exam_radar_download", args=[self.second.pk, exam.pk, score.pk],
        )).status_code, 403)
        delete_url = reverse("exam_radar_delete", args=[self.classroom.pk, exam.pk])
        self.assertEqual(self.client.get(delete_url).status_code, 405)
        self.assertTrue(ExamReport.objects.filter(pk=exam.pk).exists())

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
            self.assertEqual(b"".join(response.streaming_content), b"\x89PNG-test")
            self.client.force_login(self.teacher)
            self.assertEqual(self.client.get(reverse("download_export", args=[first[0].pk])).status_code, 403)


@override_settings(DEBUG=True, STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                                     "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class RendererTests(TestCase):
    def test_report_png_repeats_headers_and_paginates_full_notes(self):
        from .renderer import render_pages

        note = "本周作业按时完成，书写认真，订正及时；" * 35
        snapshot = {
            "classroom": "演示班级", "title": "每日综合评价表", "dates": "2026-10-17",
            "draft": True, "sources": [{"day": "2026-10-17", "revision": None, "draft": True}],
            "tables": [{
                "title": "每日评价", "headers": ["学号", "组号", "负责", "姓名", "基础分", "合计", "备注"],
                "rows": [
                    [f"{i:03}", "二组", "值日", f"测试同学{i:03}", "5", "5", note if i == 1 else ""]
                    for i in range(1, 25)
                ],
            }],
        }
        images = render_pages(snapshot, template="board/report_print.html")
        self.assertGreater(len(images), 1)
        self.assertLess(len(images), 8)
        self.assertTrue(all(image.startswith(b"\x89PNG") and len(image) > 10000 for image in images))

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
