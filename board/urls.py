from django.urls import path

from . import views
from . import journal_views
from . import exam_views

urlpatterns = [
    path("classes/<int:classroom_id>/radar/", exam_views.exam_radar, name="exam_radar"),
    path(
        "classes/<int:classroom_id>/radar/<int:exam_id>/<int:score_id>/download/",
        exam_views.exam_radar_download,
        name="exam_radar_download",
    ),
    path(
        "classes/<int:classroom_id>/radar/<int:exam_id>/delete/",
        exam_views.exam_radar_delete,
        name="exam_radar_delete",
    ),
    path("classes/<int:classroom_id>/journal/", journal_views.journal, name="journal"),
    path("classes/<int:classroom_id>/report/", journal_views.report, name="report"),
    path("classes/<int:classroom_id>/report/prepare/", journal_views.report_prepare, name="report_prepare"),
    path("reports/pages/<int:page_id>/", journal_views.report_page, name="report_page"),
    path("reports/<int:bundle_id>/download/", journal_views.report_download, name="report_download"),
    path("", views.teacher_login, name="login"),
    path("login/identities/", views.identities, name="identities"),
    path("staff-access/", views.administrator_login, name="administrator_login"),
    path("logout/", views.logout_view, name="logout"),
    path("account/first-password/", views.password_change, name="password_change_required"),
    path("account/password/", views.password_change, name="password_change"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("boards/<int:board_id>/", views.board_detail, name="board_detail"),
    path("boards/<int:board_id>/edit/<int:assignment_id>/", views.editor, name="editor"),
    path("boards/<int:board_id>/save/<int:assignment_id>/", views.submit, name="submit"),
    path("boards/<int:board_id>/action/", views.board_action, name="board_action"),
    path("boards/<int:board_id>/preview/", views.preview, name="preview"),
    path("boards/<int:board_id>/export/", views.export_images, name="export"),
    path("items/<int:item_id>/action/", views.item_action, name="item_action"),
    path("exports/<int:export_id>/", views.download_export, name="download_export"),
    path("classes/<int:classroom_id>/roster/", views.roster, name="roster"),
    path("classes/<int:classroom_id>/students/<int:student_id>/toggle/", views.deactivate_student, name="deactivate_student"),
    path("classes/<int:classroom_id>/import/", views.import_roster, name="import_roster"),
    path("classes/<int:classroom_id>/template/", views.roster_template, name="roster_template"),
    path("classes/<int:classroom_id>/assignments/", views.assignments, name="assignments"),
    path("imports/<int:import_id>/", views.import_preview, name="import_preview"),
    path("health/", views.health, name="health"),
]
