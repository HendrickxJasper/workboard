import json

from django import template

from card import services

register = template.Library()


@register.filter
def activity(card):
    return services.activity_state(card)


@register.filter
def idle_days(card):
    return services.idle_days(card)


@register.filter
def running_label(card):
    from agent.models import AgentRun

    run = card.runs.filter(status__in=AgentRun.ACTIVE_STATUSES).first()
    if run:
        return f"Claude: {run.current_step or 'working'}"
    return "Timer running" if card.timer_running else ""


@register.filter
def pending_actions(card):
    flag = getattr(card, "has_pending_actions", None)
    if flag is None:
        flag = card.actions.filter(status="proposed").exists()
    return flag


@register.filter
def score_dots(score):
    if score is None:
        return ""
    return "●" * score + "○" * (3 - score)


@register.filter
def pretty_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
