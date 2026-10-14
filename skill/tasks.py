import logging

from procrastinate.contrib.django import app

from . import services
from .models import SkillRepo

log = logging.getLogger(__name__)


@app.task(queueing_lock="pull_skill_repos", name="skill.pull_skill_repos")
def pull_skill_repos():
    services.ensure_repo_from_settings()
    for repo in SkillRepo.objects.all():
        try:
            services.pull_repo(repo)
        except services.SkillRepoError as exc:
            log.warning("Skills repo %s: %s", repo, exc)


@app.periodic(cron="*/30 * * * *", periodic_id="pull_skill_repos")
@app.task(queueing_lock="pull_skill_repos_periodic", name="skill.pull_skill_repos_periodic")
def pull_skill_repos_periodic(timestamp: int):
    pull_skill_repos()
