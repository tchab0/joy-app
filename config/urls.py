from django.contrib import admin
from django.http import HttpResponse
from django.urls import path

urlpatterns = [
    path("", lambda request: HttpResponse("JOY OK")),
    path("admin/", admin.site.urls),
]
