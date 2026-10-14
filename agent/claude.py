"""Claude triage: a small tool-use loop with read-only tools and one `submit_triage` exit.

Tools Claude gets:
- odoo_search_read: read-only lookups on an allowlist of models
- read_skill: load a team skill's SKILL.md (progressive disclosure, like Agent Skills)
- submit_triage: the structured result, including proposed actions

Claude never writes anywhere. Proposed actions are validated and executed only after approval.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

from django.conf import settings

from .actions import PAYLOAD_HELP, REQUIRED

ALLOWED_MODELS = {
    "res.partner": ["id", "name", "email", "is_company", "parent_id", "commercial_partner_id"],
    "helpdesk.ticket": ["id", "name", "partner_id", "team_id", "stage_id", "user_id", "create_date"],
    "helpdesk.team": ["id", "name"],
    "project.task": ["id", "name", "partner_id", "project_id", "stage_id", "user_ids", "date_deadline"],
    "project.project": ["id", "name", "partner_id"],
    "res.users": ["id", "name", "login"],
}
MAX_LOOKUP_ROWS = 20
CLASSIFICATIONS = ["support_request", "client_request", "internal", "fyi", "newsletter", "other"]


class TriageError(Exception):
    pass


TOOLS = [
    {
        "name": "odoo_search_read",
        "description": (
            "Read-only search in the company Odoo. Use it to find the customer (res.partner by email "
            "or domain), existing tickets, the support team or projects. Domain uses Odoo syntax, "
            'e.g. [["email", "=ilike", "%@acme.be"]]. Allowed models: ' + ", ".join(ALLOWED_MODELS)
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "enum": list(ALLOWED_MODELS)},
                "domain": {"type": "array", "items": {}},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LOOKUP_ROWS},
            },
            "required": ["model", "domain"],
        },
    },
    {
        "name": "read_skill",
        "description": "Load the full instructions of a team skill from the catalogue by slug.",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
    {
        "name": "submit_triage",
        "description": "Submit the triage result. Call exactly once, as your final step.",
        "input_schema": {
            "type": "object",
            "properties": {
                "classification": {"type": "string", "enum": CLASSIFICATIONS},
                "summary": {"type": "string", "description": "One or two sentences: what this is about."},
                "client_name": {"type": ["string", "null"]},
                "odoo_partner_id": {"type": ["integer", "null"]},
                "urgency": {"type": "string", "enum": ["low", "normal", "high"]},
                "ai_assist_score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 3,
                    "description": "0 = needs a human entirely, 3 = you can draft the complete response.",
                },
                "next_step": {
                    "type": "string",
                    "description": "The single next step for the user, imperative.",
                },
                "skills_used": {"type": "array", "items": {"type": "string"}},
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": list(REQUIRED)},
                            "title": {"type": "string"},
                            "payload": {"type": "object"},
                            "depends_on": {
                                "type": ["integer", "null"],
                                "description": "Index of an earlier action in this list whose result is needed.",
                            },
                        },
                        "required": ["type", "title", "payload"],
                    },
                },
            },
            "required": ["classification", "summary", "urgency", "ai_assist_score", "next_step", "actions"],
        },
    },
]


def system_prompt() -> str:
    user = settings.WORKBOARD_USER_NAME or "the user"
    actions = "\n".join(f"- {t}: {json.dumps(fields)}" for t, fields in PAYLOAD_HELP.items())
    return f"""You are the triage assistant on {user}'s personal work board at {settings.WORKBOARD_COMPANY_NAME}.
Each item is a card: an email, an Odoo task, ticket or activity, or a manual to-do.
For every card: understand it, identify the customer, rate urgency, rate how much you can help
(ai_assist_score 0-3), name one concrete next step, and propose actions only when they clearly help.

Rules:
- Never invent Odoo ids. Look them up with odoo_search_read; leave them null when unsure.
- Check the skill catalogue. If a skill fits the work, read it with read_skill and follow it.
- A customer email that asks for help with a problem and was sent to {user} directly instead of
  to support is a "support_request". For those, propose in this order:
  1. odoo_create_ticket for the customer's partner (the support team is filled in automatically),
  2. odoo_post_note on that ticket (depends_on 0) with your analysis of the issue and a proposed
     solution a colleague can work from,
  3. gmail_create_draft replying to the customer that support has picked it up, mentioning
     ticket {{depends_on_id}} (depends_on 0).
- Customer-facing text uses the customer's language. Internal notes use English unless the card
  is clearly in another team language.
- Newsletters and pure FYI mail: ai_assist_score 0 or 1, no actions.
- Keep proposals short and factual. You are drafting for a colleague, not the customer, unless
  it is an email draft.

Action payloads:
{actions}

Today is {date.today().isoformat()}. Finish by calling submit_triage exactly once."""


def card_context(card, skills) -> str:
    data = {
        "source": card.get_source_display(),
        "title": card.title,
        "client": (
            {
                "name": card.client.name,
                "odoo_partner_id": card.client.odoo_partner_id,
                "email_domains": card.client.email_domains,
            }
            if card.client
            else None
        ),
        "due_date": card.due_date.isoformat() if card.due_date else None,
        "content": card.raw.get("body") or card.excerpt,
        "details": {k: v for k, v in card.raw.items() if k not in ("body", "snippet")},
    }
    catalogue = "\n".join(f"- {s.slug} ({s.category}): {s.description[:300]}" for s in skills) or "(none)"
    return f"Card:\n{json.dumps(data, ensure_ascii=False, indent=2, default=str)}\n\nSkill catalogue:\n{catalogue}"


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _block_dict(block) -> dict | None:
    kind = _get(block, "type")
    if kind == "text":
        return {"type": "text", "text": _get(block, "text", "")}
    if kind == "tool_use":
        return {
            "type": "tool_use",
            "id": _get(block, "id"),
            "name": _get(block, "name"),
            "input": _get(block, "input"),
        }
    return None


def run_triage(card, *, llm, odoo=None, skills=(), read_skill: Callable | None = None, on_step=None) -> dict:
    """Run the loop. Returns {"result", "transcript", "usage", "skills_read"}."""
    on_step = on_step or (lambda text: None)
    skills_by_slug = {s.slug: s for s in skills}
    messages = [{"role": "user", "content": card_context(card, skills)}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    skills_read: list = []
    nudged = False

    for turn in range(settings.CLAUDE_MAX_TURNS):
        on_step("Reading the card" if turn == 0 else "Thinking")
        resp = llm.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=4096,
            system=system_prompt(),
            tools=TOOLS,
            messages=messages,
        )
        resp_usage = _get(resp, "usage")
        if resp_usage is not None:
            usage["input_tokens"] += _get(resp_usage, "input_tokens", 0) or 0
            usage["output_tokens"] += _get(resp_usage, "output_tokens", 0) or 0
        blocks = [b for b in (_block_dict(b) for b in _get(resp, "content", [])) if b]
        messages.append({"role": "assistant", "content": blocks})
        tool_uses = [b for b in blocks if b["type"] == "tool_use"]

        if not tool_uses:
            if nudged:
                raise TriageError("Claude stopped without submitting a triage.")
            nudged = True
            messages.append({"role": "user", "content": "Please call submit_triage now."})
            continue

        results = []
        for tu in tool_uses:
            if tu["name"] == "submit_triage":
                on_step("Writing proposal")
                return {
                    "result": tu["input"],
                    "transcript": messages,
                    "usage": usage,
                    "skills_read": skills_read,
                }
            try:
                content = _run_tool(tu, odoo, skills_by_slug, read_skill, skills_read, on_step)
                results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": content})
            except Exception as exc:  # tool errors go back to Claude, not up the stack
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": str(exc)[:500],
                        "is_error": True,
                    }
                )
        messages.append({"role": "user", "content": results})

    raise TriageError(f"No triage after {settings.CLAUDE_MAX_TURNS} turns.")


def _run_tool(tu, odoo, skills_by_slug, read_skill, skills_read, on_step) -> str:
    args = tu["input"] or {}
    if tu["name"] == "odoo_search_read":
        model = args.get("model")
        if model not in ALLOWED_MODELS:
            raise TriageError(f"Model {model!r} is not allowed.")
        if odoo is None:
            raise TriageError("Odoo is not configured.")
        on_step(f"Looking up {model} in Odoo")
        limit = min(int(args.get("limit") or 10), MAX_LOOKUP_ROWS)
        rows = odoo.search_read(model, args.get("domain") or [], ALLOWED_MODELS[model], limit=limit)
        return json.dumps(rows, ensure_ascii=False, default=str)
    if tu["name"] == "read_skill":
        skill = skills_by_slug.get(args.get("slug", ""))
        if not skill or read_skill is None:
            raise TriageError(f"Unknown skill {args.get('slug')!r}.")
        on_step(f"Reading skill {skill.slug}")
        if skill not in skills_read:
            skills_read.append(skill)
        return read_skill(skill)
    raise TriageError(f"Unknown tool {tu['name']!r}.")


def default_llm():
    if not settings.ANTHROPIC_API_KEY:
        raise TriageError("ANTHROPIC_API_KEY is not set.")
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
