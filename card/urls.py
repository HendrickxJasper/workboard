from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "card"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="card:board"), name="home"),
    path("board/", views.board, name="board"),
    path("board/counters/", views.counters, name="counters"),
    path("card/new/", views.new, name="new"),
    path("card/<int:pk>/", views.detail, name="detail"),
    path("card/<int:pk>/face/", views.face, name="face"),
    path("card/<int:pk>/move/", views.move, name="move"),
    path("card/<int:pk>/triage/", views.triage, name="triage"),
]
