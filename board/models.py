from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    display_name = models.CharField("姓名", max_length=80, blank=True)
    must_change_password = models.BooleanField("下次登录必须修改密码", default=False)

    def __str__(self):
        return self.display_name or self.username


class Subject(models.Model):
    name = models.CharField("科目", max_length=40, unique=True)
    sort_order = models.PositiveSmallIntegerField("排序", default=0)
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name = "科目"
        verbose_name_plural = "科目"

    def __str__(self):
        return self.name


class Classroom(models.Model):
    name = models.CharField("班级名称", max_length=80, unique=True)
    homeroom_teacher = models.ForeignKey(
        User,
        verbose_name="班主任",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="homeroom_classes",
    )
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "班级"
        verbose_name_plural = "班级"

    def __str__(self):
        return self.name


class TeacherAssignment(models.Model):
    teacher = models.ForeignKey(User, verbose_name="教师", on_delete=models.CASCADE, related_name="assignments")
    classroom = models.ForeignKey(Classroom, verbose_name="班级", on_delete=models.CASCADE, related_name="assignments")
    subject = models.ForeignKey(Subject, verbose_name="科目", on_delete=models.PROTECT, related_name="assignments")
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        ordering = ("classroom__name", "subject__sort_order", "subject__name", "teacher__display_name")
        constraints = [
            models.UniqueConstraint(
                fields=("teacher", "classroom", "subject"),
                name="unique_teacher_class_subject",
            )
        ]
        verbose_name = "任教关系"
        verbose_name_plural = "任教关系"

    def __str__(self):
        return f"{self.classroom} · {self.subject} · {self.teacher}"


class Student(models.Model):
    classroom = models.ForeignKey(Classroom, verbose_name="班级", on_delete=models.CASCADE, related_name="students")
    student_no = models.CharField("学号", max_length=40)
    name = models.CharField("姓名", max_length=80)
    is_active = models.BooleanField("在读", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ("student_no", "name")
        constraints = [
            models.UniqueConstraint(fields=("classroom", "student_no"), name="unique_student_no_per_class")
        ]
        verbose_name = "学生"
        verbose_name_plural = "学生"

    def __str__(self):
        return f"{self.student_no} · {self.name}"


class DailyBoard(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "进行中"
        FINALIZED = "finalized", "已定稿"

    classroom = models.ForeignKey(Classroom, verbose_name="班级", on_delete=models.CASCADE, related_name="boards")
    day = models.DateField("日期")
    title = models.CharField("榜单标题", max_length=120, blank=True, default="")
    footer = models.CharField("落款", max_length=160, blank=True, default="")
    state = models.CharField("状态", max_length=16, choices=State.choices, default=State.OPEN)
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    finalized_at = models.DateTimeField("定稿时间", null=True, blank=True)
    finalized_by = models.ForeignKey(
        User, verbose_name="定稿人", on_delete=models.SET_NULL, null=True, blank=True, related_name="finalized_boards"
    )

    class Meta:
        ordering = ("-day", "classroom__name")
        constraints = [
            models.UniqueConstraint(fields=("classroom", "day"), name="unique_board_per_class_day")
        ]
        verbose_name = "每日榜单"
        verbose_name_plural = "每日榜单"

    @property
    def is_finalized(self):
        return self.state == self.State.FINALIZED

    def __str__(self):
        return f"{self.classroom} · {self.day:%Y-%m-%d}"


class DailySubmission(models.Model):
    board = models.ForeignKey(DailyBoard, verbose_name="每日榜单", on_delete=models.CASCADE, related_name="submissions")
    assignment = models.ForeignKey(
        TeacherAssignment, verbose_name="任教关系", on_delete=models.PROTECT, related_name="submissions"
    )
    is_submitted = models.BooleanField("已提交", default=False)
    submitted_at = models.DateTimeField("提交时间", null=True, blank=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ("assignment__subject__sort_order", "assignment__subject__name", "assignment__teacher__display_name")
        constraints = [
            models.UniqueConstraint(fields=("board", "assignment"), name="unique_submission_per_assignment")
        ]
        verbose_name = "教师填报"
        verbose_name_plural = "教师填报"

    def mark_submitted(self):
        self.is_submitted = True
        self.submitted_at = timezone.now()
        self.save(update_fields=("is_submitted", "submitted_at", "updated_at"))

    def __str__(self):
        return f"{self.board} · {self.assignment.subject} · {self.assignment.teacher}"


class PraiseItem(models.Model):
    submission = models.ForeignKey(DailySubmission, verbose_name="教师填报", on_delete=models.CASCADE, related_name="items")
    title = models.CharField("表扬项目", max_length=120)
    note = models.CharField("说明", max_length=400, blank=True)
    all_students = models.BooleanField("全班同学", default=False)
    student_snapshots = models.JSONField("学生名单快照", default=list, blank=True)
    sort_order = models.PositiveSmallIntegerField("展示顺序", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "表扬项目"
        verbose_name_plural = "表扬项目"

    def __str__(self):
        return self.title


class BoardExport(models.Model):
    board = models.ForeignKey(DailyBoard, verbose_name="每日榜单", on_delete=models.CASCADE, related_name="exports")
    file = models.FileField("PNG 图片", upload_to="boards/%Y/%m/")
    created_by = models.ForeignKey(User, verbose_name="导出人", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField("导出时间", auto_now_add=True)
    revision = models.ForeignKey("BoardRevision", on_delete=models.PROTECT, related_name="exports", null=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "图片导出记录"
        verbose_name_plural = "图片导出记录"

    def __str__(self):
        return f"{self.board} · {self.created_at:%Y-%m-%d %H:%M}"


class LoginFailureBucket(models.Model):
    fingerprint = models.CharField("匿名登录标识", max_length=64, unique=True)
    window_started_at = models.DateTimeField("窗口开始", default=timezone.now)
    failures = models.PositiveSmallIntegerField("失败次数", default=0)
    locked_until = models.DateTimeField("锁定至", null=True, blank=True)

    class Meta:
        verbose_name = "登录限制记录"
        verbose_name_plural = "登录限制记录"


class RosterImport(models.Model):
    class State(models.TextChoices):
        PREVIEW = "preview", "待确认"
        IMPORTED = "imported", "已导入"
        REJECTED = "rejected", "已拒绝"

    classroom = models.ForeignKey(Classroom, verbose_name="班级", on_delete=models.CASCADE, related_name="imports")
    created_by = models.ForeignKey(User, verbose_name="导入人", on_delete=models.SET_NULL, null=True)
    state = models.CharField("状态", max_length=16, choices=State.choices, default=State.PREVIEW)
    rows = models.JSONField("预览数据", default=list)
    errors = models.JSONField("校验错误", default=list)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "学生名单导入"
        verbose_name_plural = "学生名单导入"


class BoardRevision(models.Model):
    board = models.ForeignKey(DailyBoard, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ("-number",)
        constraints = [
            models.UniqueConstraint(fields=("board", "number"), name="unique_board_revision")
        ]
