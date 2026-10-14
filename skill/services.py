"""Skills repo: clone/pull (fast-forward only) and index every SKILL.md (rules 11, 12).

Works with a Claude Code plugin marketplace layout
(plugins/<plugin>/skills/<skill>/SKILL.md, as in scrollit/claude-skills) and with
plain <category>/<skill>/SKILL.md folders. Category comes from the frontmatter
(`category` or `metadata.category`), else the plugin name, else the parent folder.
"""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
from pathlib import Path

import yaml
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.text import slugify

from .models import Skill, SkillRepo

MAX_SKILL_CHARS = 20_000


class SkillRepoError(Exception):
    pass


def repo_root(repo: SkillRepo) -> Path:
    path = Path(repo.local_path)
    return path if path.is_absolute() else Path(settings.BASE_DIR) / path


def ensure_repo_from_settings() -> SkillRepo | None:
    if not settings.SKILLS_REPO_URL and not Path(settings.SKILLS_REPO_PATH).exists():
        return None
    repo, _ = SkillRepo.objects.update_or_create(
        local_path=settings.SKILLS_REPO_PATH,
        defaults={
            "name": settings.SKILLS_REPO_NAME,
            "remote_url": settings.SKILLS_REPO_URL,
            "default_branch": settings.SKILLS_REPO_BRANCH,
        },
    )
    return repo


def _auth_args() -> list[str]:
    """Per-call auth header for a private HTTPS repo. Keeps the token out of the URL,
    the clone's .git/config and the database."""
    token = settings.SKILLS_REPO_TOKEN
    if not token:
        return []
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.extraHeader=Authorization: Basic {basic}"]


def _run_git(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # fail fast instead of waiting for a password
    return subprocess.run(
        ["git", *_auth_args(), *args], capture_output=True, text=True, timeout=timeout, env=env
    )


def _git(root: Path, *args: str) -> str:
    proc = _run_git(["-C", str(root), *args], timeout=300)
    if proc.returncode != 0:
        raise SkillRepoError(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def pull_repo(repo: SkillRepo) -> SkillRepo:
    root = repo_root(repo)
    try:
        if not (root / ".git").exists():
            if not repo.remote_url:
                raise SkillRepoError(f"{root} is not a git repo and no remote URL is set.")
            root.parent.mkdir(parents=True, exist_ok=True)
            branch = ["--branch", repo.default_branch] if repo.default_branch else []
            proc = _run_git(["clone", *branch, repo.remote_url, str(root)], timeout=600)
            if proc.returncode != 0:
                raise SkillRepoError(proc.stderr.strip())
        else:
            if _git(root, "status", "--porcelain"):
                raise SkillRepoError(
                    "Local changes in the skills clone; pull skipped. Commit or stash them first."
                )
            _git(root, "pull", "--ff-only")  # the branch the clone tracks
        repo.last_pulled_commit = _git(root, "rev-parse", "HEAD")
        repo.last_pulled_at = timezone.now()
        repo.last_error = ""
    except (SkillRepoError, subprocess.TimeoutExpired) as exc:
        repo.last_error = str(exc)[:1000]
        repo.save(update_fields=["last_error", "updated_at"])
        raise SkillRepoError(repo.last_error) from exc
    repo.save(update_fields=["last_pulled_commit", "last_pulled_at", "last_error", "updated_at"])
    reindex(repo)
    return repo


def parse_skill_file(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return (meta if isinstance(meta, dict) else {}), parts[2].lstrip()
    return {}, text


def _category(meta: dict, rel: Path) -> str:
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    explicit = meta.get("category") or metadata.get("category")
    if explicit:
        return str(explicit)
    parts = rel.parts
    if len(parts) >= 5 and parts[0] == "plugins" and parts[2] == "skills":
        return parts[1]
    return parts[-3] if len(parts) >= 3 else "other"


@transaction.atomic
def reindex(repo: SkillRepo) -> int:
    root = repo_root(repo)
    seen = set()
    for path in sorted(root.rglob("SKILL.md")):
        if ".git" in path.parts:
            continue
        rel = path.relative_to(root)
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, _ = parse_skill_file(text)
        slug = slugify(meta.get("name") or path.parent.name)[:100]
        if slug in seen:
            continue
        seen.add(slug)
        Skill.objects.update_or_create(
            repo=repo,
            slug=slug,
            defaults={
                "category": _category(meta, rel)[:100],
                "path": str(rel),
                "description": str(meta.get("description", ""))[:2000],
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            },
        )
    repo.skills.exclude(slug__in=seen).delete()
    return len(seen)


def read_skill(skill: Skill) -> str:
    path = repo_root(skill.repo) / skill.path
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_SKILL_CHARS:
        text = text[:MAX_SKILL_CHARS] + "\n\n[truncated]"
    return text


def catalogue() -> list[Skill]:
    return list(Skill.objects.select_related("repo").order_by("category", "slug"))


def record_usage(run, skills):
    skills = list(skills)
    if not skills:
        return
    run.skills_used.add(*skills)
    Skill.objects.filter(pk__in=[s.pk for s in skills]).update(
        usage_count=F("usage_count") + 1, last_used_at=timezone.now()
    )
