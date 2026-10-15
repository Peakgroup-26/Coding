"""The chat panel: talk to the AI about a job, and it looks things up and makes changes with the
tools in chat_tools.py.

How the conversation is kept (the API requires this): each job has one active session. Its system
prompt (instructions, the job, and the memories at that moment) and its tool list are fixed when
the session starts. After that, messages are only ever appended, exactly as they were sent and
received, thinking blocks included. The job's current state goes into each new user message, not
into the system prompt, so nothing earlier ever changes. When a conversation gets long, it's
summarised and a new session starts from the summary.
"""
import json
import logging
import os
import threading
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import chat_tools, memory
from .ai import AIUnavailable
from .models import ChatMessage, ChatSession, Job, User

log = logging.getLogger(__name__)

MAX_STEPS = 16  # model calls per message
MAX_SESSION_CHARS = 400_000  # roughly 100k tokens of history before it's summarised
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()

SYSTEM = """You are the estimating assistant inside Peak Take-off, working with the estimators at Peak \
Plumbing & Gas Services (Sunshine Coast, Queensland) on one tender. You can look at the job and change it \
with your tools. Everything you change is recorded in the audit log under the name of the person you're \
talking to.

How to work:
- Quantities come from the drawings and the app's own measuring. Never make up quantities, rates or \
percentages. If you're asked for something the drawings don't show, say so and offer to add a line for \
the person's own figure.
- What you add or trace is a suggestion until it's approved. Use the approve tools only when the person \
asks you to approve.
- Before changing or deleting more than 20 items, say what you'll do and ask them to confirm, unless \
they've already said exactly that.
- If the person tells you a preference, a rule or a correction that should carry into future work (a \
material Peak always uses, how a consultant draws a service, a typical allowance), save it with \
`remember`: scope "company" for every job, "client" for this client's jobs, "job" for this job only. \
Don't save what's already in memory. If a memory turns out to be wrong, use `forget`.
- The person may be talking through a microphone and listening, so answer in plain spoken English: \
short (two to four sentences) unless they ask for detail, no tables or markdown. Australian English, metres.
- Each message from the person starts with the job's current state in <job_state> tags. Use it, and the \
tools, rather than guessing.

The job: {job}

{memories}"""

SUMMARY_PROMPT = """Summarise this conversation between an estimator and the AI assistant about one job, so the \
assistant can carry on in a new conversation. Keep: what the estimator asked for, what was changed (with \
numbers), decisions and preferences, and anything still to do. Plain text, under 400 words.

{transcript}"""


class ChatModel(Protocol):
    def respond(self, system: str, tools: list[dict], messages: list[dict]) -> tuple[str, list[dict], str]:
        """Returns (stop_reason, content blocks as dicts, model)."""

    def summarise(self, prompt: str) -> str: ...


class ClaudeChat:
    def __init__(self):
        import anthropic

        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = os.environ.get("TAKEOFF_AI_MODEL", "claude-opus-5-5")

    def _create(self, **kw):
        try:
            return self.client.beta.messages.create(model=self.model, max_tokens=16000, fallbacks="default", **kw)
        except self.anthropic.AuthenticationError as e:
            raise AIUnavailable("The AI service rejected the credentials. Check ANTHROPIC_API_KEY.") from e
        except self.anthropic.RateLimitError as e:
            raise AIUnavailable("The AI service is busy. Try again in a minute.") from e
        except self.anthropic.APIStatusError as e:
            raise AIUnavailable(f"The AI service returned an error ({e.status_code}).") from e
        except self.anthropic.APIConnectionError as e:
            raise AIUnavailable("Couldn't reach the AI service.") from e
        except self.anthropic.AnthropicError as e:
            raise AIUnavailable(f"The AI service isn't set up correctly: {e}") from e

    def respond(self, system, tools, messages):
        r = self._create(
            system=system, tools=tools, messages=messages,
            # Server-side fallback if a request is declined; and if the history ever fails the
            # thinking-block check, drop the stale thinking rather than failing the turn.
            betas=["server-side-fallback-2026-07-01", "thinking-binding-controls-2026-08-01"],
            thinking={"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
            output_config={"effort": "medium"},
            cache_control={"type": "ephemeral"},
        )
        return r.stop_reason, [b.to_dict() for b in r.content], r.model

    def summarise(self, prompt):
        r = self._create(messages=[{"role": "user", "content": prompt}], betas=["server-side-fallback-2026-07-01"],
                         output_config={"effort": "low"})
        return next((b.text for b in r.content if b.type == "text"), "")


_override: ChatModel | None = None


def set_model(m: ChatModel | None) -> None:
    """For tests."""
    global _override
    _override = m


def get_model() -> ChatModel | None:
    if _override is not None:
        return _override
    if os.environ.get("TAKEOFF_AI", "").lower() == "claude" and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        try:
            return ClaudeChat()
        except Exception as e:
            log.warning("Chat AI unavailable: %s", e)
    return None


def _lock(job_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(job_id, threading.Lock())


# --- sessions ---
def active_session(db: Session, job: Job, summary: str = "") -> ChatSession:
    s = db.scalar(select(ChatSession).where(ChatSession.job_id == job.id, ChatSession.active.is_(True)))
    if s is not None:
        return s
    mems = memory.as_text(memory.for_job(db, job))
    system = SYSTEM.format(
        job=f"{job.name} (job {job.id}, {'civil BOQ' if job.kind == 'civil' else 'hydraulic take-off'}, client {job.client or 'not set'})",
        memories=("What you remember from earlier work:\n" + mems) if mems else "You have no memories saved yet.")
    if summary:
        system += "\n\nSummary of the earlier conversation about this job:\n" + summary
    tools = chat_tools.schemas_for(job.kind or "hydraulic")
    s = ChatSession(job_id=job.id, system=system, tool_names=[t["name"] for t in tools], summary=summary)
    db.add(s)
    db.flush()
    return s


def new_session(db: Session, job: Job) -> ChatSession:
    for s in db.scalars(select(ChatSession).where(ChatSession.job_id == job.id, ChatSession.active.is_(True))):
        s.active = False
    db.flush()
    return active_session(db, job)


def _history(db: Session, session: ChatSession) -> list[ChatMessage]:
    return list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.id)))


def _maybe_compact(db: Session, job: Job, session: ChatSession, model: ChatModel) -> ChatSession:
    history = _history(db, session)
    if sum(len(json.dumps(m.content)) for m in history) < MAX_SESSION_CHARS:
        return session
    transcript = "\n".join(f"{m.role}: {m.text}" + (f" [did: {'; '.join(a['summary'] for a in m.actions or [])}]" if m.actions else "")
                           for m in history if not m.hidden and (m.text or m.actions))
    summary = model.summarise(SUMMARY_PROMPT.format(transcript=transcript[-200_000:]))
    session.active = False
    db.flush()
    return active_session(db, job, summary=summary)


def visible(db: Session, job: Job) -> list[dict]:
    """The messages to show in the chat panel (current session, plus a marker if earlier ones were summarised)."""
    s = db.scalar(select(ChatSession).where(ChatSession.job_id == job.id, ChatSession.active.is_(True)))
    if s is None:
        return []
    names = {u.id: (u.name or u.email) for u in db.scalars(select(User))}
    out = [{"id": 0, "role": "note", "text": "Earlier conversation summarised.", "actions": []}] if s.summary else []
    for m in _history(db, s):
        if m.hidden or not (m.text or m.actions):
            continue
        out.append({"id": m.id, "role": m.role, "text": m.text, "actions": m.actions or [],
                    "user": names.get(m.user_id, "") if m.role == "user" else "", "at": m.created_at})
    return out


# --- a turn ---
def send(db: Session, job: Job, user: User, text: str) -> dict:
    """Handle one message from a person: run the AI and its tools until it has answered."""
    model = get_model()
    if model is None:
        raise AIUnavailable("The AI isn't switched on for this server (no API key), so the chat can't answer.")
    lock = _lock(job.id)
    if not lock.acquire(timeout=120):
        raise AIUnavailable("Someone else is talking to the AI about this job right now. Try again in a moment.")
    try:
        session = _maybe_compact(db, job, active_session(db, job), model)
        first_new = (db.scalar(select(ChatMessage.id).order_by(ChatMessage.id.desc()).limit(1)) or 0)
        state = chat_tools.snapshot_text(db, job)
        user_content = [{"type": "text", "text": f"<job_state>\n{state}\n</job_state>\n\n{text}"}]
        db.add(ChatMessage(session_id=session.id, role="user", content=user_content, text=text, user_id=user.id))
        db.commit()
        tools = [t for t in chat_tools.schemas_for(job.kind or "hydraulic") if t["name"] in (session.tool_names or [])]
        ctx = chat_tools.Ctx(db, job, user)
        changed = False
        for _ in range(MAX_STEPS):
            messages = [{"role": m.role, "content": m.content} for m in _history(db, session)]
            stop, content, _model = model.respond(session.system, tools, messages)
            said = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            if stop == "refusal":
                said = said or "Sorry, I can't help with that one."
            assistant = ChatMessage(session_id=session.id, role="assistant", content=content, text=said)
            db.add(assistant)
            db.commit()
            if stop != "tool_use":
                if stop == "max_tokens":
                    assistant.text = (said + "\n\n(My answer was cut short. Ask me to carry on.)").strip()
                    db.commit()
                break
            results, actions = [], []
            for block in content:
                if block.get("type") != "tool_use":
                    continue
                try:
                    out, action = chat_tools.run(ctx, block["name"], block.get("input") or {})
                    db.commit()
                    if action:
                        actions.append({"tool": block["name"], "summary": action})
                        changed = True
                    results.append({"type": "tool_result", "tool_use_id": block["id"], "content": out[:50_000]})
                except chat_tools.ToolError as e:
                    db.rollback()
                    results.append({"type": "tool_result", "tool_use_id": block["id"], "content": str(e), "is_error": True})
                except Exception as e:  # a bug in a tool: tell the AI, keep the conversation going
                    log.exception("Chat tool %s failed", block.get("name"))
                    db.rollback()
                    results.append({"type": "tool_result", "tool_use_id": block["id"],
                                    "content": f"That didn't work ({e.__class__.__name__}).", "is_error": True})
            if actions:
                assistant.actions = actions
            db.add(ChatMessage(session_id=session.id, role="user", content=results, hidden=True, user_id=user.id))
            db.commit()
        new = [m for m in visible(db, job) if m["id"] > first_new]
        return {"messages": new, "changed": changed}
    finally:
        lock.release()
