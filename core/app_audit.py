"""Prompt-audit helper layer.

Wraps every LLM call so input/output text, tokens, latency, model, route,
stage, session_id, and token_id are captured to the audit collection. The
audit is observational only — it must never change application behavior,
never block, and never raise.

Schema version: 1 (current baseline as of 2026-05-13). All audit docs written
through `record_llm_call` and `record_audit_row` set `schema_version: 1`.
When changing the doc shape in a way that affects consumer parsing, bump
this number and document the migration in `docs/ops/audit_schema_history.md`
(create file when first migration lands).

Public API:
    extract_usage(msg) -> (input_tokens, output_tokens, model_or_none)
    record_llm_call(...)       — direct write of an LLM-call row (kind="llm_call")
    record_audit_row(...)      — direct write of a non-LLM event row (kind="audit_event")
    audit_llm_call(...)        — context manager wrapping LLM.invoke
"""
from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

# WIB display zone for the readable `timestamp_wib` field; storage `timestamp`
# stays UTC for sortability and consistency with other system collections.
_WIB = ZoneInfo("Asia/Jakarta")


def extract_usage(msg: Any) -> tuple[int, int, str | None]:
    """Return (input_tokens, output_tokens, model_or_none) from any of three
    known LLM-message shapes:

    - LangChain newer: msg.usage_metadata = {"input_tokens", "output_tokens"}
    - LangChain/OpenAI older: msg.response_metadata = {"token_usage": {...}, "model_name": ...}
    - Raw Anthropic SDK: msg.usage = Usage(input_tokens=..., output_tokens=...)

    Falls back to (0, 0, None) on unknown shape so audit rows always write.
    """
    # 1) LangChain new shape
    um = getattr(msg, "usage_metadata", None)
    if um:
        rm = getattr(msg, "response_metadata", {}) or {}
        return (
            int(um.get("input_tokens", 0) or 0),
            int(um.get("output_tokens", 0) or 0),
            rm.get("model_name"),
        )

    # 2) LangChain old / OpenAI shape
    rm = getattr(msg, "response_metadata", {}) or {}
    tu = rm.get("token_usage") or {}
    if tu:
        in_tok = int(tu.get("input_tokens", tu.get("prompt_tokens", 0)) or 0)
        out_tok = int(tu.get("output_tokens", tu.get("completion_tokens", 0)) or 0)
        return in_tok, out_tok, rm.get("model_name")

    # 3) Raw Anthropic SDK Message.usage
    u = getattr(msg, "usage", None)
    if u is not None:
        return (
            int(getattr(u, "input_tokens", 0) or 0),
            int(getattr(u, "output_tokens", 0) or 0),
            getattr(msg, "model", None),
        )

    return 0, 0, None


def _truncate(s: Any, n: int) -> Any:
    """Cap a string at n characters; suffix with `…` when truncated.
    Returns None when input is None. Coerces non-string input via str()."""
    if s is None:
        return None
    s = str(s)
    if len(s) > n:
        return s[: n - 1] + "…"
    return s


def _msg_to_dict(m: Any) -> dict:
    """Coerce a LangChain BaseMessage (or any obj with .type/.content,
    or already a dict) into {"role": str, "content": str}."""
    if isinstance(m, dict):
        return {"role": str(m.get("role", "")), "content": str(m.get("content", ""))}
    role = getattr(m, "type", None) or getattr(m, "role", None) or "user"
    content = getattr(m, "content", "")
    return {"role": str(role), "content": str(content)}


def _serialize_prompt(
    prompt: Any,
    *,
    mode: str,
    max_chars: int,
):
    """Apply PROMPT_STORE_MODE to a prompt value.

    - "text": flatten message list to a single text string and truncate
    - "messages": list of {role, content} dicts, each content truncated
    - "off": None (audit row still writes; just no body)
    """
    mode = (mode or "text").strip().lower()
    if mode == "off":
        return None

    if isinstance(prompt, str):
        if mode == "messages":
            return [{"role": "user", "content": _truncate(prompt, max_chars)}]
        return _truncate(prompt, max_chars)

    if isinstance(prompt, (list, tuple)):
        dicts = [_msg_to_dict(m) for m in prompt]
        if mode == "messages":
            return [{"role": d["role"], "content": _truncate(d["content"], max_chars)} for d in dicts]
        # text mode: flatten role: content lines, then truncate the whole blob
        flat = "\n".join(f"{d['role']}: {d['content']}" for d in dicts)
        return _truncate(flat, max_chars)

    # Unknown shape — coerce to str
    return _truncate(str(prompt), max_chars) if mode != "messages" else [
        {"role": "user", "content": _truncate(str(prompt), max_chars)}
    ]


from datetime import datetime, timezone

_writer_instance = None
_writer_lock = None


def _get_writer():
    """Lazily build the writer once per process. Tests may override
    `_writer_instance` directly to inject a fake."""
    global _writer_instance, _writer_lock
    if _writer_instance is not None:
        return _writer_instance
    if _writer_lock is None:
        import threading
        _writer_lock = threading.Lock()
    with _writer_lock:
        if _writer_instance is None:
            from infra.prompt_audit_repo import build_writer
            _writer_instance = build_writer()
    return _writer_instance


def record_llm_call(
    *,
    route: str,
    stage: str,
    session_id: str,
    token_id: str | None,
    prompt,
    response: str,
    model: str | None,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    extras: dict | None = None,
    error: str | None = None,
    kind: str = "llm_call",
) -> None:
    """Direct write of an LLM-call audit row.

    Errors are swallowed: failed writes never propagate to the caller.
    """
    try:
        from core.app_config import Config
        cfg = Config()
        mode = (cfg.PROMPT_STORE_MODE or "text").strip().lower()
        max_chars = int(cfg.PROMPT_MAX_CHARS or 6000)

        _now_utc = datetime.now(timezone.utc)
        doc = {
            "timestamp": _now_utc,
            "timestamp_wib": _now_utc.astimezone(_WIB).strftime("%Y-%m-%d %H:%M:%S WIB"),
            "sessionId": session_id or "",
            "tokenId": token_id,
            "route": route,
            "stage": stage,
            "kind": kind,
            "schema_version": 1,
            "model": model,
            "latency_ms": int(latency_ms or 0),
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "llm_prompt": _serialize_prompt(prompt, mode=mode, max_chars=max_chars),
            "llm_output": (None if mode == "off" else _truncate(response, max_chars)),
            "extras": extras or {},
            "error": error,
        }
        _get_writer().write(doc)
    except Exception:
        # Audit must never raise into the caller.
        pass


def record_audit_row(
    *,
    stage: str,
    session_id: str,
    extras: dict | None = None,
    route: str = "system_detection",
    token_id: str | None = None,
    error: str | None = None,
) -> None:
    """Direct write of a non-LLM audit row.

    Companion to `record_llm_call` for orchestrator-stage events that don't
    correspond to an LLM call: `ooc_handler`, `ooc_suppression_fallthrough`,
    `abandonment_handler`, `language_fallback`, etc.

    Parity with `record_llm_call`:
    - Uses the same `_get_writer()` singleton → identical bounded-queue +
      worker-pool + drop-on-full semantics (PROMPT_AUDIT_QUEUE_SIZE +
      PROMPT_AUDIT_WORKERS via infra/prompt_audit_repo.py)
    - Same backend selection (PROMPT_AUDIT_BACKEND: mongo | noop)
    - Same test-fixture support — overriding `_writer_instance` directly
      flows through both helpers identically
    - Errors swallowed: failed writes never propagate to the caller

    Schema differences from LLM rows:
    - `kind` = "audit_event" (vs "llm_call" for record_llm_call)
    - No `llm_prompt`, `llm_output`, `model`, `latency_ms`,
      `input_tokens`, `output_tokens` fields
    - `extras` carries the stage-specific payload (typed dict from caller;
      e.g., `OOCAuditMetadata.model_dump()` for ooc_handler)

    Per spec §7.4 + §9 audit row taxonomy.
    """
    try:
        _now_utc = datetime.now(timezone.utc)
        doc = {
            "timestamp": _now_utc,
            "timestamp_wib": _now_utc.astimezone(_WIB).strftime("%Y-%m-%d %H:%M:%S WIB"),
            "sessionId": session_id or "",
            "tokenId": token_id,
            "route": route,
            "stage": stage,
            "kind": "audit_event",
            "schema_version": 1,
            "extras": extras or {},
            "error": error,
        }
        _get_writer().write(doc)
    except Exception:
        # Audit must never raise into the caller.
        pass


import time
from contextlib import contextmanager


class _AuditCtx:
    """Mutable context handed back from the audit_llm_call CM. Callers set
    response/tokens/model on it; the CM's __exit__ writes the audit doc.

    `latency_ms` is set by the CM's finally block before the doc is written,
    so callers reading it after the `with` block see the final value."""

    __slots__ = ("response_text", "input_tokens", "output_tokens", "model", "extras_extra", "latency_ms")

    def __init__(self):
        self.response_text = ""
        self.input_tokens = 0
        self.output_tokens = 0
        self.model = None
        self.extras_extra = {}
        self.latency_ms = 0

    def set_response_from_message(self, msg) -> None:
        """Pull tokens + model from a LangChain / Anthropic SDK message and
        capture .content as the response text."""
        in_tok, out_tok, model = extract_usage(msg)
        self.input_tokens = in_tok
        self.output_tokens = out_tok
        if model:
            self.model = model
        text = getattr(msg, "content", "") or ""
        self.response_text = str(text)

    def set_response(
        self,
        response_text: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str | None = None,
    ) -> None:
        self.response_text = response_text or ""
        self.input_tokens = int(input_tokens or 0)
        self.output_tokens = int(output_tokens or 0)
        if model:
            self.model = model


@contextmanager
def audit_llm_call(
    *,
    route: str,
    stage: str,
    session_id: str,
    token_id: str | None,
    prompt,
    model: str | None = None,
    extras: dict | None = None,
):
    """Context manager that times an LLM call and writes one audit row.

    Usage:
        with audit_llm_call(route=..., stage=..., session_id=..., token_id=...,
                            prompt=messages) as ctx:
            msg = LLM.invoke(messages)
            ctx.set_response_from_message(msg)
        # audit row written on __exit__

    On exception inside the block: an audit row is still written with
    `error=str(exc)` and the exception is re-raised.
    """
    ctx = _AuditCtx()
    if model:
        ctx.model = model
    t0 = time.perf_counter()
    err: str | None = None
    try:
        yield ctx
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        ctx.latency_ms = latency_ms
        # Resolve model: explicit > from message > cfg default
        chosen_model = ctx.model
        if not chosen_model:
            try:
                from core.app_config import Config
                chosen_model = Config().ANTHROPIC_MODEL
            except Exception:
                chosen_model = None
        merged_extras = dict(extras or {})
        if ctx.extras_extra:
            merged_extras.update(ctx.extras_extra)
        record_llm_call(
            route=route,
            stage=stage,
            session_id=session_id,
            token_id=token_id,
            prompt=prompt,
            response=ctx.response_text,
            model=chosen_model,
            latency_ms=latency_ms,
            input_tokens=ctx.input_tokens,
            output_tokens=ctx.output_tokens,
            extras=merged_extras,
            error=err,
        )
