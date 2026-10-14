import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from card.models import Card
from card.views import drawer_context

from . import services
from .models import AgentRun, ProposedAction


def _drawer(request, card_pk, *, error=""):
    card = Card.objects.with_activity().select_related("client").get(pk=card_pk)
    return render(request, "card/partials/drawer.html", drawer_context(card, error=error, oob_face=True))


@login_required
@require_POST
def approve(request, pk):
    action = get_object_or_404(ProposedAction, pk=pk)
    error = ""
    try:
        payload = None
        if "payload" in request.POST:
            try:
                payload = json.loads(request.POST["payload"])
            except json.JSONDecodeError as exc:
                raise ValidationError(f"Payload is not valid JSON: {exc.msg}") from exc
        services.approve_action(action, payload=payload)
    except ValidationError as exc:
        error = "; ".join(exc.messages)
    return _drawer(request, action.card_id, error=error)


@login_required
@require_POST
def reject(request, pk):
    action = get_object_or_404(ProposedAction, pk=pk)
    error = ""
    try:
        services.reject_action(action)
    except ValidationError as exc:
        error = "; ".join(exc.messages)
    return _drawer(request, action.card_id, error=error)


@login_required
@require_POST
def approve_all(request, pk):
    run = get_object_or_404(AgentRun, pk=pk)
    error = ""
    try:
        services.approve_all(run)
    except ValidationError as exc:
        error = "; ".join(exc.messages)
    return _drawer(request, run.card_id, error=error)
