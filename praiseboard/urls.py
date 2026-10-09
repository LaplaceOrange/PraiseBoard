from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_header = "表扬榜管理"
admin.site.site_title = "表扬榜管理"
admin.site.index_title = "管理全部班级与教师"

urlpatterns = [
    path("", include("board.urls")),
    path("staff-room/", admin.site.urls),
    path("favicon.ico", RedirectView.as_view(url="/static/icons/award.svg", permanent=False)),
]
