"""Plain factory functions and fakes for external services."""

import itertools

from agent.models import AgentRun, ProposedAction
from card.models import Card, Client
from connector.models import Connection
from skill.models import Skill, SkillRepo

_seq = itertools.count(1)


def client(**kw):
    n = next(_seq)
    kw.setdefault("name", f"Client {n}")
    return Client.objects.create(**kw)


def card(**kw):
    n = next(_seq)
    kw.setdefault("source", Card.Source.MANUAL)
    kw.setdefault("title", f"Card {n}")
    if kw["source"] != Card.Source.MANUAL:
        kw.setdefault("external_id", f"ext-{n}")
    return Card.objects.create(**kw)


def connection(kind="odoo"):
    return Connection.objects.get_or_create(kind=kind, defaults={"name": kind})[0]


def run(card_obj, **kw):
    kw.setdefault("kind", AgentRun.Kind.TRIAGE)
    return AgentRun.objects.create(card=card_obj, **kw)


def action(run_obj, **kw):
    kw.setdefault("action_type", "create_todo")
    kw.setdefault("payload", {"title": "Follow up"})
    return ProposedAction.objects.create(run=run_obj, card=run_obj.card, **kw)


def skill(**kw):
    repo = kw.pop("repo", None) or SkillRepo.objects.create(name="Skills", local_path="/tmp/none")
    kw.setdefault("slug", f"skill-{next(_seq)}")
    return Skill.objects.create(repo=repo, path=f"{kw['slug']}/SKILL.md", **kw)


# --- fakes -------------------------------------------------------------------------
class FakeOdoo:
    url = "https://odoo.test"

    def __init__(self, data=None):
        self.data = data or {}  # model -> list of records returned by search_read
        self.calls = []
        self.next_id = 500

    def search_read(self, model, domain, fields, *, limit=None, order=None):
        self.calls.append(("search_read", model, domain))
        return list(self.data.get(model, []))

    def create(self, model, vals):
        self.calls.append(("create", model, vals))
        self.next_id += 1
        return self.next_id

    def message_post(self, model, res_id, body, *, note=True):
        self.calls.append(("message_post", model, res_id, body))
        return 900

    def record_url(self, model, res_id):
        return f"{self.url}/odoo/{model}/{res_id}"


class FakeGmail:
    def __init__(self, threads=None):
        self.threads = threads or {}
        self.drafts = []

    def list_thread_ids(self, query, max_results):
        return list(self.threads)

    def get_thread(self, thread_id):
        return self.threads[thread_id]

    def create_draft(self, **kw):
        self.drafts.append(kw)
        return {"draft_id": f"d{len(self.drafts)}", "url": "https://mail.test/draft"}


class FakeLLM:
    """Mimics anthropic.Anthropic().messages.create with scripted responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def tool_use(name, tool_input, tool_id="tu_1"):
    return {
        "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


def thread(thread_id="t1", subject="Help", from_email="tom@acme.test", snippet="Hi"):
    return {
        "thread_id": thread_id,
        "subject": subject,
        "from_name": "Tom",
        "from_email": from_email,
        "to": "me@company.test",
        "message_id": "<m1@acme.test>",
        "date": "",
        "message_count": 1,
        "snippet": snippet,
        "body": snippet,
        "history_id": "1",
    }
