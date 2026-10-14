from django.urls import path

from . import views

app_name = "agent"

urlpatterns = [
    path("action/<int:pk>/approve/", views.approve, name="approve"),
    path("action/<int:pk>/reject/", views.reject, name="reject"),
    path("run/<int:pk>/approve-all/", views.approve_all, name="approve_all"),
]
