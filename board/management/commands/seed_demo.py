from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from board.models import Classroom, Student, Subject, TeacherAssignment, User


class Command(BaseCommand):
    help = "Create explicitly synthetic local demo data. Never runs automatically."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo data is only allowed with DJANGO_DEBUG=1.")
        classroom, _ = Classroom.objects.get_or_create(name="演示班级")
        teacher, created = User.objects.get_or_create(
            username="demo-teacher", defaults={"display_name": "演示老师", "must_change_password": True}
        )
        if created:
            teacher.set_password("123456")
            teacher.save()
        classroom.homeroom_teacher = teacher
        classroom.save()
        for name in ("语文", "数学"):
            subject, _ = Subject.objects.get_or_create(name=name)
            TeacherAssignment.objects.get_or_create(teacher=teacher, classroom=classroom, subject=subject)
        for number in range(1, 41):
            Student.objects.get_or_create(
                classroom=classroom, student_no=f"{number:02d}", defaults={"name": f"示例同学{number:02d}"}
            )
        self.stdout.write(self.style.SUCCESS("Synthetic demo class created. Teacher initial password: 123456"))
