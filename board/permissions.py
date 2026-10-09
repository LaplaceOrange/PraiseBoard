from django.db.models import Q

from .models import Classroom, DailyBoard, TeacherAssignment


def is_admin(user):
    return bool(user.is_authenticated and user.is_active and user.is_superuser)


def visible_classrooms(user):
    if is_admin(user):
        return Classroom.objects.filter(is_active=True)
    return Classroom.objects.filter(is_active=True).filter(
        Q(homeroom_teacher=user) | Q(assignments__teacher=user, assignments__is_active=True)
    ).distinct()


def can_manage_class(user, classroom):
    return bool(user.is_authenticated and user.is_active and (
        is_admin(user) or classroom.homeroom_teacher_id == user.id
    ))


def can_access_class(user, classroom):
    if not user.is_authenticated or not user.is_active:
        return False
    if is_admin(user) or classroom.homeroom_teacher_id == user.id:
        return True
    return TeacherAssignment.objects.filter(
        teacher=user,
        classroom=classroom,
        is_active=True,
    ).exists()


def teacher_assignments(user, classroom=None):
    assignments = TeacherAssignment.objects.filter(
        teacher=user,
        is_active=True,
        classroom__is_active=True,
        subject__is_active=True,
    ).select_related("classroom", "subject", "teacher")
    if classroom is not None:
        assignments = assignments.filter(classroom=classroom)
    return assignments


def can_edit_submission(user, board: DailyBoard, assignment: TeacherAssignment):
    if board.is_finalized or assignment.classroom_id != board.classroom_id:
        return False
    if is_admin(user) or board.classroom.homeroom_teacher_id == user.id:
        return True
    return assignment.teacher_id == user.id and assignment.is_active
