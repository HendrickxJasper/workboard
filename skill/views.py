from itertools import groupby

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from . import services
from .models import Skill, SkillRepo


def _context(error=""):
    services.ensure_repo_from_settings()
    skills = Skill.objects.select_related("repo").order_by("category", "slug")
    groups = [(cat, list(items)) for cat, items in groupby(skills, key=lambda s: s.category)]
    return {"repos": SkillRepo.objects.all(), "groups": groups, "error": error}


@login_required
def index(request):
    return render(request, "skill/index.html", _context())


@login_required
@require_POST
def pull(request, pk):
    repo = get_object_or_404(SkillRepo, pk=pk)
    error = ""
    try:
        services.pull_repo(repo)
    except services.SkillRepoError as exc:
        error = str(exc)
    return render(request, "skill/partials/content.html", _context(error))
