from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from . import services
from .models import Connection


def _rows():
    services.get_connection(Connection.Kind.ODOO)
    services.get_connection(Connection.Kind.GMAIL)
    configured = {
        "odoo": bool(settings.ODOO_URL and settings.ODOO_API_KEY),
        "gmail": Path(settings.GMAIL_TOKEN_FILE).exists(),
    }
    return [
        {"conn": c, "configured": configured.get(c.kind, False), "cards": c.cards.count()}
        for c in Connection.objects.all()
    ]


@login_required
def index(request):
    return render(
        request,
        "connector/index.html",
        {"rows": _rows(), "claude_ready": bool(settings.ANTHROPIC_API_KEY), "model": settings.CLAUDE_MODEL},
    )


@login_required
@require_POST
def sync(request, pk):
    conn = get_object_or_404(Connection, pk=pk)
    stats = services.sync_odoo() if conn.kind == Connection.Kind.ODOO else services.sync_gmail()
    row = next(r for r in _rows() if r["conn"].pk == pk)
    return render(request, "connector/partials/row.html", {"row": row, "stats": stats})
