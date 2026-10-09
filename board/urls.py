from django.urls import path

from . import views

urlpatterns = [
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
