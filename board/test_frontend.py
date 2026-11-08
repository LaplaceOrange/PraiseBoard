import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from .models import (
    Classroom, DailyBoard, DailySubmission, ExamReport, ExamScore, Student,
    Subject, TeacherAssignment, User,
)
from .services import change_board_state, save_items


@override_settings(
    DEBUG=True,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class FrontendTests(StaticLiveServerTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            "ui-demo", password="Demo-browser-password", display_name="演示老师"
        )
        self.classroom = Classroom.objects.create(name="演示班级", homeroom_teacher=self.teacher)
        self.empty_class = Classroom.objects.create(name="演示空班")
        self.students = [
            Student.objects.create(
                classroom=self.classroom, student_no=f"{number:02d}", name=f"示例同学{number:02d}"
            )
            for number in range(1, 41)
        ]
        self.assignments = [
            TeacherAssignment.objects.create(
                teacher=self.teacher, classroom=self.classroom, subject=Subject.objects.create(name=name)
            )
            for name in ("语文", "数学")
        ]
        self.board = DailyBoard.objects.create(classroom=self.classroom, day=timezone.localdate())
        save_items(self.teacher, self.board.pk, self.assignments[1].pk, [{
            "title": "作业认真", "note": "书写工整，认真完成每一道题。",
            "student_ids": [student.pk for student in self.students[:2]],
        }], 0)
        history = DailyBoard.objects.create(
            classroom=self.classroom, day=timezone.localdate() - timedelta(days=1)
        )
        self.history = history
        save_items(self.teacher, history.pk, self.assignments[0].pk, [{
            "title": "课堂积极", "all_students": True, "student_ids": [],
        }], 0)
        change_board_state(self.teacher, history.pk, "finalize", 1)
        self.client.force_login(self.teacher)
        self.session_key = self.client.session.session_key
        self.admin = User.objects.create_superuser(
            "ui-admin", password="Admin-browser-password", display_name="演示管理员"
        )
        admin_client = Client()
        admin_client.force_login(self.admin)
        self.admin_session_key = admin_client.session.session_key
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch()
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.measurements = []

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        super().tearDown()

    def authenticate(self, admin=False):
        self.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.admin_session_key if admin else self.session_key,
            "url": self.live_server_url,
        }])

    def submission_state(self):
        # Playwright's sync runner owns an event loop; query Django outside that thread.
        def read():
            submission = DailySubmission.objects.get(board_id=self.board.pk, assignment_id=self.assignments[0].pk)
            item = submission.items.get()
            return submission.is_submitted, item.title, len(item.student_snapshots)
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(read).result()

    def visit(self, path):
        response = self.page.goto(self.live_server_url + path)
        self.assertEqual(response.status, 200)
        self.page.wait_for_load_state("networkidle")

    def check_layout(self, scenario):
        measurements = self.page.evaluate("""() => {
          const style = selector => {
            const element = document.querySelector(selector);
            if (!element) return null;
            const computed = getComputedStyle(element);
            return Object.fromEntries(
              ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'color',
               'backgroundColor', 'marginBottom', 'paddingLeft', 'paddingRight',
               'maxWidth', 'gridTemplateColumns'].map(key => [key, computed[key]])
            );
          };
          return {
            width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
            h1: document.querySelectorAll('h1').length,
            assets: [...document.images].filter(image => !image.complete || !image.naturalWidth).map(image => image.src),
            body: style('body'), title: style('h1'), section: style('h2'),
            metadata: style('.pb-muted'), action: style('.pb-button--primary'),
            content: style('.pb-content'), shell: style('.pb-shell'),
            tableAlignment: [...document.querySelectorAll('tbody tr')].every(row =>
              [...row.cells].every((cell, index) => {
                const header = cell.closest('table').querySelectorAll('th')[index];
                return !header || cell.colSpan > 1 ||
                  getComputedStyle(cell).textAlign === getComputedStyle(header).textAlign;
              })
            )
          };
        }""")
        self.assertEqual(measurements["h1"], 1, scenario)
        self.assertLessEqual(measurements["scrollWidth"], measurements["width"], scenario)
        self.assertEqual(measurements["assets"], [], scenario)
        self.assertTrue(measurements["tableAlignment"], scenario)
        self.assertEqual(self.errors, [], scenario)
        self.measurements.append({"scenario": scenario, **measurements})
        if measurements["width"] >= 760:
            self.assertFalse(self.page.locator(".pb-mobile-menu").is_visible())
            self.assertFalse(self.page.locator(".pb-nav-close").is_visible())
        if os.environ.get("PB_CAPTURE"):
            directory = Path(settings.BASE_DIR) / "output" / "playwright"
            directory.mkdir(parents=True, exist_ok=True)
            suffix = os.environ.get("PB_CAPTURE")
            self.page.screenshot(path=str(directory / f"{scenario}-{suffix}.png"), full_page=True)
            self.page.screenshot(path=str(directory / f"{scenario}-viewport-{suffix}.png"))
            (directory / f"measurements-{suffix}.json").write_text(
                json.dumps(self.measurements, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def test_responsive_pages_and_navigation(self):
        self.visit("/")
        self.check_layout("login-desktop")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.check_layout("login-mobile")
        self.authenticate()
        pages = [
            ("dashboard", "/dashboard/"),
            ("editor", f"/boards/{self.board.pk}/edit/{self.assignments[1].pk}/"),
            ("roster", f"/classes/{self.classroom.pk}/roster/"),
            ("detail", f"/boards/{self.board.pk}/"),
            ("password", "/account/password/"),
        ]
        for name, path in pages:
            for width, height, device in [(1440, 900, "desktop"), (390, 844, "mobile")]:
                self.page.set_viewport_size({"width": width, "height": height})
                self.visit(path)
                self.check_layout(f"{name}-{device}")
        self.visit("/dashboard/")
        trigger = self.page.get_by_role("button", name="打开导航")
        trigger.click()
        expect(trigger).to_have_attribute("aria-expanded", "true")
        expect(self.page.locator("[data-close-nav]")).to_be_focused()
        self.assertTrue(self.page.locator(".pb-main").evaluate("element => element.inert"))
        self.page.locator(".pb-sidebar button[type=submit]").focus()
        self.page.keyboard.press("Tab")
        expect(self.page.locator(".pb-sidebar .pb-brand")).to_be_focused()
        self.page.keyboard.press("Shift+Tab")
        expect(self.page.locator(".pb-sidebar button[type=submit]")).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(trigger).to_have_attribute("aria-expanded", "false")
        expect(trigger).to_be_focused()
        self.assertFalse(self.page.locator(".pb-main").evaluate("element => element.inert"))
        trigger.click()
        self.page.set_viewport_size({"width": 760, "height": 900})
        self.assertFalse(self.page.locator(".pb-sidebar").evaluate("element => element.inert"))
        self.assertFalse(self.page.locator(".pb-main").evaluate("element => element.inert"))
        self.page.set_viewport_size({"width": 320, "height": 740})
        self.check_layout("dashboard-small")
        self.page.locator(".pb-topbar-context").evaluate(
            "element => element.textContent = '演示名称特别长的班级名称用于检查窄屏换行与布局'"
        )
        self.check_layout("dashboard-long-text")
        self.page.locator(".pb-mobile-brand").focus()
        outline = self.page.locator(".pb-mobile-brand").evaluate("element => getComputedStyle(element).outlineWidth")
        self.assertEqual(outline, "3px")

    def test_journal_note_and_report_clipboard_flow_on_mobile(self):
        self.authenticate()
        today = timezone.localdate().isoformat()
        journal_url = f"/classes/{self.classroom.pk}/journal/?day={today}&tab=daily"
        for width, height, device in [(1440, 900, "desktop"), (390, 844, "mobile")]:
            self.page.set_viewport_size({"width": width, "height": height})
            self.visit(journal_url)
            expect(self.page.get_by_role("heading", name="每日综合评价")).to_be_visible()
            self.check_layout(f"journal-{device}")
        self.assertTrue(self.page.locator(".pb-table-wrap").evaluate(
            "element => element.scrollWidth >= element.clientWidth"
        ))

        self.page.set_viewport_size({"width": 390, "height": 844})
        self.visit(f"/classes/{self.classroom.pk}/journal/?day={today}&tab=entries")
        self.page.locator("#entry-category").select_option("note")
        self.page.locator("#student-search").fill("示例同学01")
        self.page.locator("[name=student_ids]").first.check()
        expect(self.page.locator("#entry-points")).to_be_disabled()
        self.page.locator("#entry-reason").fill("家校联系")
        self.page.locator("#entry-note").fill("已通知家长")
        self.page.get_by_role("button", name="保存记录").click()
        expect(self.page.locator(".pb-custom-score-record")).to_contain_text("家校联系")
        expect(self.page.locator(".pb-custom-score-record")).to_contain_text("已通知家长")
        expect(self.page.locator(".pb-custom-score-record")).to_contain_text("0.00 分")

        seating_url = f"/classes/{self.classroom.pk}/journal/?day={today}&tab=seating"
        for width, height, device in [(1440, 900, "desktop"), (390, 844, "mobile")]:
            self.page.set_viewport_size({"width": width, "height": height})
            self.visit(seating_url)
            expect(self.page.get_by_role("link", name="按座位排")).to_be_visible()
            expect(self.page.locator(".pb-custom-seat").first).to_contain_text("学号")
            self.check_layout(f"seating-{device}")
        self.page.get_by_role("link", name="按学号排").click()
        expect(self.page.locator(".pb-custom-seat").first).not_to_contain_text("示例同学")
        self.page.locator(".pb-custom-seat").first.click()
        self.page.locator("#seat-reason").fill("课堂发言积极")
        self.page.get_by_role("button", name="加 2 分").click()
        self.page.get_by_role("link", name="按座位排").click()
        expect(self.page.locator(".pb-custom-seat.is-positive.is-strong")).to_have_count(1)

        self.visit(f"/classes/{self.classroom.pk}/journal/?day={today}&tab=settings")
        expect(self.page.locator("#base-points")).to_have_value("5")
        expect(self.page.locator("#calendar-enabled")).to_have_value(
            "1" if timezone.localdate().weekday() < 5 else "0"
        )
        self.check_layout("journal-settings-mobile")

        self.page.add_init_script("""(() => {
          window.__clipboardWrites = 0;
          window.__clipboardFails = false;
          Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: { write: async () => {
              window.__clipboardWrites += 1;
              if (window.__clipboardFails) throw new DOMException("denied", "NotAllowedError");
            } }
          });
          window.ClipboardItem = class { constructor(data) { this.data = data; } };
        })();""")
        self.page.route("**/classes/*/report/prepare/", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"download": "/fixture.zip", "pages": [{"number": 1, "url": "/fixture.png"}]}),
        ))
        self.page.route("**/fixture.png", lambda route: route.fulfill(
            status=200, content_type="image/png",
            body=bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                               "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082"),
        ))
        report_url = f"/classes/{self.classroom.pk}/report/?day={today}&kind=evaluation"
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.visit(report_url)
        self.check_layout("report-desktop")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.visit(report_url)
        self.check_layout("report-mobile")
        self.page.get_by_role("button", name="生成图片").click()
        copy = self.page.get_by_role("button", name="复制图片")
        expect(copy).to_be_visible()
        expect(self.page.locator("#report-status")).to_have_text("已生成 1 页图片。")
        copy.click()
        expect(self.page.locator("#report-status")).to_have_text("已复制第 1 页图片。")
        self.assertEqual(self.page.evaluate("window.__clipboardWrites"), 1)
        self.page.evaluate("window.__clipboardFails = true")
        copy.click()
        expect(self.page.locator("#report-status")).to_contain_text("未能复制图片")
        expect(self.page.locator('#report-pages a[download="report-1.png"]')).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_radar_chart_responsive_and_png_clipboard(self):
        def create_exam():
            exam = ExamReport.objects.create(classroom=self.classroom, title="合成成绩测试")
            fields = {
                "chinese": 96, "mathematics": 102, "english": 90,
                "physics": 80, "morals": 78, "history": 84, "pe": 48,
            }
            student = self.students[0]
            ExamScore.objects.create(
                exam=exam, student=student, student_no=student.student_no,
                student_name=student.name, **fields,
            )
            for student_no, multiple in [("60", .6), ("75", .75), ("85", .85), ("92", .92)]:
                ExamScore.objects.create(
                    exam=exam, student_no=student_no, student_name=f"{student_no}线",
                    is_reference=True,
                    chinese=120 * multiple, mathematics=120 * multiple, english=120 * multiple,
                    physics=100 * multiple, morals=100 * multiple, history=100 * multiple,
                    pe=60 * multiple,
                )
            return exam.pk

        with ThreadPoolExecutor(max_workers=1) as executor:
            exam_id = executor.submit(create_exam).result()
        self.authenticate()
        self.page.add_init_script("""(() => {
          window.__clipboardWrites = 0;
          window.__clipboardFails = false;
          Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: { write: async () => {
              window.__clipboardWrites += 1;
              if (window.__clipboardFails) throw new DOMException("denied", "NotAllowedError");
            } }
          });
          window.ClipboardItem = class { constructor(data) { this.data = data; } };
        })();""")
        url = f"/classes/{self.classroom.pk}/radar/?exam={exam_id}"
        for width, height, device in [(1440, 900, "desktop"), (390, 844, "mobile")]:
            self.page.set_viewport_size({"width": width, "height": height})
            self.visit(url)
            expect(self.page.get_by_role("heading", name="成绩雷达图")).to_be_visible()
            expect(self.page.locator("#radar-chart polygon")).to_have_count(10)
            expect(self.page.locator("#radar-image-status")).to_contain_text("图片已准备好")
            expect(self.page.locator("#radar-png-download")).to_be_enabled()
            self.check_layout(f"radar-{device}")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.visit(url)
        expect(self.page.locator("#radar-image-status")).to_contain_text("图片已准备好")
        self.page.get_by_role("button", name="复制图片").click()
        expect(self.page.locator("#radar-image-status")).to_have_text("已复制图片，可直接粘贴到微信。")
        self.assertEqual(self.page.evaluate("window.__clipboardWrites"), 1)
        self.page.evaluate("window.__clipboardFails = true")
        self.page.get_by_role("button", name="复制图片").click()
        expect(self.page.locator("#radar-image-status")).to_contain_text("未能复制图片")
        expect(self.page.get_by_role("button", name="下载 PNG")).to_be_enabled()
        self.assertEqual(self.errors, [])

    def test_login_and_roster_search(self):
        self.visit("/")
        expect(self.page.locator("#identity")).to_be_disabled()
        self.page.locator("#classroom").select_option(str(self.empty_class.pk))
        expect(self.page.locator("#login-feedback")).to_contain_text("尚未分配")
        expect(self.page.locator("#identity")).to_be_disabled()
        self.page.locator("#classroom").select_option(str(self.classroom.pk))
        expect(self.page.locator("#identity")).to_be_enabled()
        self.page.locator("#identity").select_option(str(self.assignments[0].pk))
        self.page.locator("#password").fill("Demo-browser-password")
        self.page.get_by_role("button", name="显示密码").click()
        expect(self.page.locator("#password")).to_have_attribute("type", "text")
        self.page.get_by_role("button", name="隐藏密码").click()
        expect(self.page.locator("#password")).to_have_attribute("type", "password")
        self.page.get_by_role("button", name="进入工作台").click()
        self.page.wait_for_url("**/dashboard/")
        self.visit(f"/classes/{self.classroom.pk}/roster/")
        search = self.page.get_by_role("searchbox", name="搜索学生")
        search.fill("不存在")
        expect(self.page.locator("[data-search-empty]")).to_be_visible()
        search.fill("示例同学01")
        expect(self.page.locator("#roster-table tbody tr:visible")).to_have_count(1)
        search.fill("")
        expect(self.page.locator("#roster-table tbody tr:visible")).to_have_count(40)

    def test_praise_names_headings_and_preview(self):
        self.authenticate()
        for width, height, device in [(1440, 900, "desktop"), (390, 844, "mobile")]:
            self.page.set_viewport_size({"width": width, "height": height})
            for scenario, path in [
                ("praise-dashboard", "/dashboard/"),
                ("praise-detail", f"/boards/{self.board.pk}/"),
            ]:
                self.visit(path)
                row = self.page.locator(".pb-praise-row").first
                expect(row.locator("h3")).to_have_text("示例同学01、示例同学02")
                expect(row.locator("p").nth(0)).to_have_text("表扬项目：作业认真")
                expect(row.locator("p").nth(1)).to_have_text("原因与备注：书写工整，认真完成每一道题。")
                expect(row.locator("p").nth(2)).to_have_text("科目：数学 · 教师：演示老师")
                self.check_layout(f"{scenario}-{device}")
            self.visit(f"/boards/{self.board.pk}/preview/")
            self.page.wait_for_function("window.boardReady === true")
            row = self.page.locator(".print-item").first
            expect(row.locator("h3")).to_have_text("示例同学01示例同学02")
            expect(row.locator(".print-reason")).to_have_text("表扬项目：作业认真")
            expect(row.locator(".print-note")).to_have_text("原因与备注：书写工整，认真完成每一道题。")
            expect(row.locator(".print-attribution")).to_have_text("科目：数学 · 教师：演示老师")
            self.assertTrue(row.evaluate("element => element.firstElementChild.tagName === 'H3'"))
            self.check_layout(f"praise-preview-{device}")
        self.visit(f"/boards/{self.history.pk}/")
        expect(self.page.locator(".pb-praise-row h3")).to_have_text("全班同学")
        expect(self.page.locator(".pb-praise-row .pb-muted")).to_have_text("科目：语文 · 教师：演示老师")
        self.visit(f"/boards/{self.history.pk}/preview/")
        self.page.wait_for_function("window.boardReady === true")
        expect(self.page.locator(".print-item h3")).to_have_text("全班同学")
        expect(self.page.locator(".print-attribution")).to_have_text("科目：语文 · 教师：演示老师")

    def test_editor_selection_error_and_real_save(self):
        self.authenticate()
        self.visit(f"/boards/{self.board.pk}/edit/{self.assignments[0].pk}/")
        search = self.page.get_by_role("searchbox", name="搜索姓名或学号")
        search.fill("不存在")
        expect(self.page.locator(".pb-student-empty")).to_be_visible()
        expect(self.page.locator("#editor-save-state")).to_have_text("尚未修改")
        search.fill("示例同学01")
        expect(self.page.locator(".pb-student-option:visible")).to_have_count(1)
        self.page.locator("[name=student]").first.check()
        expect(self.page.locator("[data-selected-count]")).to_have_text("已选 1 人")
        self.page.get_by_role("button", name="清空选择").click()
        expect(self.page.locator("[data-selected-count]")).to_have_text("已选 0 人")
        search.fill("")
        self.page.locator("[name=all_students]").check()
        expect(self.page.locator("[data-selected-count]")).to_have_text("全班 40 人")
        expect(self.page.locator("[name=student]").first).to_be_disabled()
        self.page.get_by_role("button", name="清空选择").click()
        self.page.get_by_role("textbox", name="项目名称").fill("认真思考")
        self.page.locator("[name=student]").first.check()
        self.page.route("**/save/**", lambda route: route.abort())
        self.page.get_by_role("button", name="保存草稿").click()
        expect(self.page.locator("#editor-error")).to_contain_text("网络连接失败")
        expect(self.page.get_by_role("button", name="保存草稿")).to_be_enabled()
        expect(self.page.locator("[name=title]")).to_have_value("认真思考")
        self.page.unroute("**/save/**")
        self.page.get_by_role("button", name="保存草稿").click()
        self.page.wait_for_url("**/dashboard/**")
        self.assertEqual(self.submission_state(), (False, "认真思考", 1))
        self.visit(f"/boards/{self.board.pk}/edit/{self.assignments[0].pk}/")
        self.page.get_by_role("button", name="添加表扬项目").click()
        expect(self.page.locator(".pb-item-editor")).to_have_count(2)
        self.page.get_by_role("button", name="删除项目").last.click()
        expect(self.page.locator(".pb-item-editor")).to_have_count(1)
        self.page.get_by_role("button", name="提交填报").click()
        self.page.wait_for_url("**/dashboard/**")
        self.assertTrue(self.submission_state()[0])

    def test_admin_shared_workspace_and_responsive_pages(self):
        self.authenticate(admin=True)
        pages = [
            ("admin-index", reverse("admin:index")),
            ("admin-teachers", reverse("admin:board_user_changelist")),
            ("admin-teacher-form", reverse("admin:board_user_change", args=[self.teacher.pk])),
            ("admin-class-form", reverse("admin:board_classroom_change", args=[self.classroom.pk])),
            ("admin-subjects", reverse("admin:board_subject_changelist")),
            ("admin-password", reverse("admin:board_user_force_password", args=[self.teacher.pk])),
            ("admin-board", reverse("admin:board_dailyboard_change", args=[self.board.pk])),
        ]
        for name, path in pages:
            for width, height, device in [(1440, 900, "desktop"), (390, 844, "mobile")]:
                self.page.set_viewport_size({"width": width, "height": height})
                self.visit(path)
                self.check_layout(f"{name}-{device}")
                expect(self.page.locator(".pb-sidebar .pb-nav[aria-current=page]")).to_have_text("全站管理")
                expect(self.page.locator(".pb-topbar-context")).to_have_text("全站管理")
                self.assertEqual(
                    self.page.locator("body").evaluate("element => getComputedStyle(element).backgroundColor"),
                    "rgb(248, 250, 251)",
                )
                expect(self.page.locator("#header, #nav-sidebar, .theme-toggle")).to_have_count(0)
                self.assertTrue(self.page.locator(".submit-row input[type=submit]").evaluate_all(
                    "elements => elements.every(element => element.getBoundingClientRect().height < 80)"
                ))
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.visit(reverse("admin:index"))
        trigger = self.page.get_by_role("button", name="打开导航")
        trigger.click()
        expect(self.page.locator("[data-close-nav]")).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.visit(reverse("admin:board_subject_add") + "?_popup=1")
        expect(self.page.locator(".pb-sidebar")).to_have_count(0)
        expect(self.page.locator("body.pb-admin.popup.model-subject.change-form")).to_have_count(1)
        expect(self.page.locator("input[name=_popup]")).to_have_value("1")
        self.assertEqual(self.errors, [])

    def test_admin_search_filter_and_form_save(self):
        self.authenticate(admin=True)
        self.visit(reverse("admin:board_user_changelist"))
        self.page.locator("#searchbar").fill(self.teacher.username)
        self.page.locator("#changelist-search input[type=submit]").click()
        expect(self.page.locator("#result_list tbody tr")).to_have_count(1)
        expect(self.page.locator("#result_list")).to_contain_text("演示老师")
        self.visit(reverse("admin:board_student_changelist") + "?is_active__exact=1")
        expect(self.page.locator("#result_list tbody tr")).to_have_count(40)
        self.visit(reverse("admin:board_subject_add"))
        self.page.locator("#id_name").fill("演示新增科目")
        self.page.locator("input[name=_save]").click()
        self.page.wait_for_url("**/board/subject/")
        expect(self.page.locator("#result_list")).to_contain_text("演示新增科目")
        expect(self.page.locator(".pb-message--success")).to_be_visible()
        self.visit(reverse("admin:board_user_force_password", args=[self.teacher.pk]))
        self.page.locator("#id_password").fill("123456")
        self.page.get_by_role("button", name="重置密码").click()
        expect(self.page.locator(".errornote")).to_have_text("新密码不能全部是数字。")
        self.assertEqual(self.errors, [])

    def test_admin_navigation_preserves_selected_class(self):
        self.authenticate(admin=True)
        for width, height, device, classroom in [
            (1440, 900, "desktop", self.empty_class),
            (390, 844, "mobile", self.classroom),
        ]:
            self.page.set_viewport_size({"width": width, "height": height})
            self.visit(f"/dashboard/?classroom={classroom.pk}")
            if device == "mobile":
                self.page.get_by_role("button", name="打开导航").click()
            self.page.locator(".pb-sidebar").get_by_role("link", name="全站管理").click()
            self.page.wait_for_url("**/staff-room/")
            for scenario in ("admin-navigation-index", "admin-navigation-list"):
                sidebar = self.page.locator(".pb-sidebar")
                if device == "mobile":
                    self.page.get_by_role("button", name="打开导航").click()
                expect(sidebar.get_by_role("link", name="学生名单")).to_have_attribute(
                    "href", reverse("roster", args=[classroom.pk])
                )
                expect(sidebar.get_by_role("link", name="任教关系")).to_have_attribute(
                    "href", reverse("assignments", args=[classroom.pk])
                )
                expect(sidebar.get_by_role("link", name="每日填报")).to_have_attribute(
                    "href", f"/dashboard/?classroom={classroom.pk}"
                )
                if device == "mobile":
                    expect(sidebar.get_by_role("link", name="学生名单")).to_be_visible()
                    expect(sidebar.get_by_role("link", name="任教关系")).to_be_visible()
                    self.page.wait_for_function(
                        "Math.abs(document.querySelector('.pb-sidebar').getBoundingClientRect().left) < 1"
                    )
                self.check_layout(f"{scenario}-{device}")
                if device == "mobile":
                    sidebar.locator("[data-close-nav]").click()
                if scenario == "admin-navigation-index":
                    self.page.locator(
                        f'.pb-custom-admin a[href="{reverse("admin:board_user_changelist")}"]'
                    ).first.click()
                    self.page.wait_for_url("**/board/user/")
            if device == "mobile":
                self.page.get_by_role("button", name="打开导航").click()
            self.page.locator(".pb-sidebar").get_by_role("link", name="学生名单").click()
            self.page.wait_for_url(f"**/classes/{classroom.pk}/roster/")
            expect(self.page.locator(".pb-topbar-context")).to_have_text(classroom.name)
        self.assertEqual(self.errors, [])
