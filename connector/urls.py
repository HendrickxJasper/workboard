from django.urls import path

from . import views

app_name = "connector"

urlpatterns = [
    path("", views.index, name="index"),
    path("<int:pk>/sync/", views.sync, name="sync"),
]
