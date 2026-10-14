from django.urls import path

from . import views

app_name = "skill"

urlpatterns = [
    path("", views.index, name="index"),
    path("repo/<int:pk>/pull/", views.pull, name="pull"),
]
