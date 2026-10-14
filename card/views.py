from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from agent.services import queue_run

from . import services
from .models import Card, Client


def _filters(request) -> dict:
    state = request.GET.get("state") or None
    return {
        "client_id": request.GET.get("client") or None,
        "source": request.GET.get("source") or None,
        "state": state if state in (services.RUNNING, services.IDLE) else None,
    }


def _card(pk) -> Card:
    return get_object_or_404(Card.objects.with_activity().select_related("client"), pk=pk)


def drawer_context(card: Card, **extra) -> dict:
    runs = card.runs.prefetch_related("actions", "actions__depends_on", "skills_used")[:5]
    return {"card": card, "runs": runs, **extra}


@login_required
def board(request):
    filters = _filters(request)
    ctx = {
        "columns": services.board_columns(**filters),
        "filters": filters,
        "clients": Client.objects.filter(cards__isnull=False).distinct(),
        "sources": Card.Source.choices,
        "counters": services.counters(),
        "open_card": request.GET.get("card"),
    }
    if request.htmx and request.htmx.target == "board":
        return render(request, "card/partials/board.html", ctx)
    return render(request, "card/board.html", ctx)


@login_required
def counters(request):
    return render(request, "card/partials/counters.html", {"counters": services.counters()})


@login_required
def face(request, pk):
    return render(request, "card/partials/card_face.html", {"card": _card(pk)})


@login_required
def detail(request, pk):
    if not request.htmx:
        return redirect(f"{reverse('card:board')}?card={pk}")
    return render(request, "card/partials/drawer.html", drawer_context(_card(pk)))


@login_required
@require_POST
def move(request, pk):
    card = get_object_or_404(Card, pk=pk)
    try:
        services.move_card(card, request.POST.get("column", ""), int(request.POST.get("position", 0)))
    except (ValidationError, ValueError):
        response = render(request, "card/partials/board.html", {"columns": services.board_columns()})
        response["HX-Retarget"] = "#board"
        response["HX-Reswap"] = "innerHTML"
        return response
    return render(
        request, "card/partials/move_result.html", {"card": _card(pk), "counters": services.counters()}
    )


@login_required
@require_POST
def triage(request, pk):
    card = get_object_or_404(Card, pk=pk)
    queue_run(card, "triage")
    card = _card(pk)
    return render(request, "card/partials/drawer.html", drawer_context(card, oob_face=True))


@login_required
@require_POST
def new(request):
    try:
        card = services.create_manual_card(title=request.POST.get("title", ""))
    except ValidationError as exc:
        return render(request, "card/partials/quick_add.html", {"error": exc.messages[0]})
    return render(request, "card/partials/quick_add.html", {"new_card": _card(card.pk)})
