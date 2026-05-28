"""Unit tests for the prompt-audit helper layer.

Run (pytest available):
    python -m pytest tests/test_prompt_audit.py -v

Run (stdlib only, no pytest):
    python tests/test_prompt_audit.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ===== extract_usage =====

class _FakeLCNew:
    """LangChain newer shape — usage_metadata is the source of truth."""
    def __init__(self, in_tok, out_tok, model=None):
        self.usage_metadata = {"input_tokens": in_tok, "output_tokens": out_tok}
        self.response_metadata = {"model_name": model} if model else {}


class _FakeLCOldOpenAI:
    """LangChain older / OpenAI shape — token_usage with prompt_/completion_ keys."""
    def __init__(self, in_tok, out_tok, model=None):
        self.response_metadata = {
            "token_usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok},
            "model_name": model,
        }


class _FakeRawSDK:
    """Raw Anthropic SDK Message shape — .usage with input_tokens / output_tokens."""
    class _U:
        def __init__(self, in_tok, out_tok):
            self.input_tokens = in_tok
            self.output_tokens = out_tok
    def __init__(self, in_tok, out_tok, model=None):
        self.usage = self._U(in_tok, out_tok)
        self.model = model


class _FakeUnknown:
    pass


def test_extract_usage_langchain_new():
    from core.app_audit import extract_usage
    msg = _FakeLCNew(12, 34, model="claude-sonnet-4-6")
    assert extract_usage(msg) == (12, 34, "claude-sonnet-4-6")


def test_extract_usage_openai_old():
    from core.app_audit import extract_usage
    msg = _FakeLCOldOpenAI(7, 9, model="gpt-4o")
    assert extract_usage(msg) == (7, 9, "gpt-4o")


def test_extract_usage_raw_sdk():
    from core.app_audit import extract_usage
    msg = _FakeRawSDK(5, 6, model="claude-sonnet-4-6")
    assert extract_usage(msg) == (5, 6, "claude-sonnet-4-6")


def test_extract_usage_unknown_falls_back_to_zeros():
    from core.app_audit import extract_usage
    assert extract_usage(_FakeUnknown()) == (0, 0, None)


# ===== _truncate / _serialize_prompt =====

def test_truncate_short_string_unchanged():
    from core.app_audit import _truncate
    assert _truncate("hello", 100) == "hello"


def test_truncate_long_string_capped_with_ellipsis():
    from core.app_audit import _truncate
    s = "x" * 100
    out = _truncate(s, 10)
    assert len(out) == 10
    assert out.endswith("…")


def test_truncate_none_passthrough():
    from core.app_audit import _truncate
    assert _truncate(None, 100) is None


def test_serialize_prompt_text_mode_flattens_messages():
    """text mode: list of LC-style messages collapses to one string."""
    from core.app_audit import _serialize_prompt

    class _M:
        def __init__(self, role, content):
            self.type = role  # LangChain BaseMessage uses .type
            self.content = content

    msgs = [_M("system", "You are a helper."), _M("human", "Hi.")]
    out = _serialize_prompt(msgs, mode="text", max_chars=1000)
    assert isinstance(out, str)
    assert "You are a helper." in out
    assert "Hi." in out


def test_serialize_prompt_messages_mode_returns_list_of_dicts():
    from core.app_audit import _serialize_prompt

    class _M:
        def __init__(self, role, content):
            self.type = role
            self.content = content

    msgs = [_M("system", "S"), _M("human", "H")]
    out = _serialize_prompt(msgs, mode="messages", max_chars=1000)
    assert isinstance(out, list)
    assert out == [{"role": "system", "content": "S"}, {"role": "human", "content": "H"}]


def test_serialize_prompt_off_mode_returns_none():
    from core.app_audit import _serialize_prompt
    out = _serialize_prompt("anything", mode="off", max_chars=1000)
    assert out is None


# ===== writers =====

def test_noop_writer_write_does_nothing():
    from infra.prompt_audit_repo import NoopPromptAuditWriter
    w = NoopPromptAuditWriter()
    # Should not raise, should not need any setup.
    w.write({"foo": "bar"})
    w.close()


def test_writer_abc_cannot_instantiate():
    from infra.prompt_audit_repo import PromptAuditWriter
    try:
        PromptAuditWriter()
    except TypeError:
        return
    raise AssertionError("PromptAuditWriter() should be abstract")


class _FakeColl:
    def __init__(self):
        self.inserted = []
        self.indexes = []

    def insert_one(self, doc):
        self.inserted.append(doc)
        return type("R", (), {"inserted_id": len(self.inserted)})()

    def create_index(self, keys, **kwargs):
        self.indexes.append((tuple(keys), kwargs))


class _FakeMongoClient:
    def __init__(self, coll):
        self._coll = coll

    def __getitem__(self, db_name):
        return type("DB", (), {"__getitem__": lambda self, name, c=self._coll: c})()

    def close(self):
        pass


def test_mongo_writer_inserts_doc_and_creates_indexes():
    from infra.prompt_audit_repo import MongoPromptAuditWriter

    fake_coll = _FakeColl()
    fake_client = _FakeMongoClient(fake_coll)
    w = MongoPromptAuditWriter(
        client_factory=lambda: fake_client,
        db_name="test_db",
        coll_name="query_recording",
    )
    w._sync_write_for_test({"sessionId": "s1", "stage": "x"})
    assert len(fake_coll.inserted) == 1
    assert fake_coll.inserted[0]["sessionId"] == "s1"
    # Indexes ensured exactly once
    assert len(fake_coll.indexes) == 3
    w.close()


def test_mongo_writer_index_ensure_only_runs_once():
    from infra.prompt_audit_repo import MongoPromptAuditWriter

    fake_coll = _FakeColl()
    fake_client = _FakeMongoClient(fake_coll)
    w = MongoPromptAuditWriter(
        client_factory=lambda: fake_client,
        db_name="test_db",
        coll_name="query_recording",
    )
    w._sync_write_for_test({"sessionId": "s1"})
    w._sync_write_for_test({"sessionId": "s2"})
    assert len(fake_coll.inserted) == 2
    assert len(fake_coll.indexes) == 3  # not 6
    w.close()


def test_mongo_writer_async_write_eventually_inserts():
    """write() returns immediately; the doc lands via the worker."""
    import time
    from infra.prompt_audit_repo import MongoPromptAuditWriter

    fake_coll = _FakeColl()
    fake_client = _FakeMongoClient(fake_coll)
    w = MongoPromptAuditWriter(
        client_factory=lambda: fake_client,
        db_name="db", coll_name="c",
        queue_size=8, workers=1,
    )
    w.write({"sessionId": "s1"})
    # Give worker up to 1s to drain.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and len(fake_coll.inserted) < 1:
        time.sleep(0.01)
    assert len(fake_coll.inserted) == 1
    w.close()


def test_mongo_writer_drops_on_full_queue():
    """When queue is full, write() is non-blocking and increments dropped."""
    import threading
    from infra.prompt_audit_repo import MongoPromptAuditWriter

    fake_coll = _FakeColl()
    fake_client = _FakeMongoClient(fake_coll)

    # Block the worker so the queue fills up
    block = threading.Event()
    orig_insert = fake_coll.insert_one
    def slow_insert(doc):
        block.wait()
        return orig_insert(doc)
    fake_coll.insert_one = slow_insert

    w = MongoPromptAuditWriter(
        client_factory=lambda: fake_client,
        db_name="db", coll_name="c",
        queue_size=2, workers=1,
    )
    # First put kicks the worker (now blocked on insert), next ones fill the queue
    for i in range(20):
        w.write({"i": i})
    assert w.dropped >= 1
    block.set()
    w.close()


def test_build_writer_default_mongo():
    os.environ.pop("PROMPT_AUDIT_BACKEND", None)
    from infra.prompt_audit_repo import build_writer, MongoPromptAuditWriter
    w = build_writer(client_factory=lambda: _FakeMongoClient(_FakeColl()))
    assert isinstance(w, MongoPromptAuditWriter)
    w.close()


def test_build_writer_noop():
    os.environ["PROMPT_AUDIT_BACKEND"] = "noop"
    try:
        from infra.prompt_audit_repo import build_writer, NoopPromptAuditWriter
        w = build_writer()
        assert isinstance(w, NoopPromptAuditWriter)
        w.close()
    finally:
        os.environ.pop("PROMPT_AUDIT_BACKEND", None)


def test_build_writer_postgres_raises_not_implemented():
    os.environ["PROMPT_AUDIT_BACKEND"] = "postgres"
    try:
        from infra.prompt_audit_repo import build_writer
        try:
            build_writer()
        except NotImplementedError:
            return
        raise AssertionError("postgres backend should raise NotImplementedError")
    finally:
        os.environ.pop("PROMPT_AUDIT_BACKEND", None)


# ===== record_llm_call / audit_llm_call =====

class _CapturingWriter:
    def __init__(self):
        self.docs = []
    def write(self, doc): self.docs.append(doc)
    def close(self): pass


def _install_capturing_writer():
    """Replace the lazy writer in core.app_audit with a capturing instance."""
    import core.app_audit as audit_mod
    cap = _CapturingWriter()
    audit_mod._writer_instance = cap
    return cap


def test_record_llm_call_writes_full_doc():
    from core.app_audit import record_llm_call
    cap = _install_capturing_writer()
    record_llm_call(
        route="meeting_arrangement",
        stage="propose",
        session_id="s1",
        token_id="t1",
        prompt="hello",
        response="hi back",
        model="claude-sonnet-4-6",
        latency_ms=42,
        input_tokens=10,
        output_tokens=5,
    )
    assert len(cap.docs) == 1
    d = cap.docs[0]
    assert d["sessionId"] == "s1"
    assert d["tokenId"] == "t1"
    assert d["route"] == "meeting_arrangement"
    assert d["stage"] == "propose"
    assert d["model"] == "claude-sonnet-4-6"
    assert d["latency_ms"] == 42
    assert d["input_tokens"] == 10
    assert d["output_tokens"] == 5
    assert d["llm_prompt"] == "hello"
    assert d["llm_output"] == "hi back"
    assert d["kind"] == "llm_call"
    assert d["schema_version"] == 1
    assert d["error"] is None
    assert "timestamp" in d
    # Display field: human-readable WIB string alongside UTC ISODate
    assert "timestamp_wib" in d
    assert d["timestamp_wib"].endswith(" WIB")
    assert len(d["timestamp_wib"]) == len("YYYY-MM-DD HH:MM:SS WIB")


def test_record_llm_call_timestamp_wib_is_utc_plus_7():
    """Verify timestamp_wib is exactly 7h ahead of timestamp (UTC)."""
    from datetime import datetime
    cap = _install_capturing_writer()
    from core.app_audit import record_llm_call
    record_llm_call(
        route="r", stage="s", session_id="x", token_id=None,
        prompt="p", response="r",
        model="m", latency_ms=1, input_tokens=0, output_tokens=0,
    )
    d = cap.docs[0]
    utc_dt = d["timestamp"]
    wib_str = d["timestamp_wib"]
    # parse "YYYY-MM-DD HH:MM:SS WIB" back to a naive datetime
    parsed_wib = datetime.strptime(wib_str.replace(" WIB", ""), "%Y-%m-%d %H:%M:%S")
    # difference between WIB-naive and UTC-aware (stripped) should be 7h ± 1s
    delta = abs((parsed_wib - utc_dt.replace(tzinfo=None)).total_seconds() - 7 * 3600)
    assert delta < 2.0, f"expected ~7h offset between UTC and WIB, got delta {delta}s"


class _FakeCfg:
    """Minimal stand-in for Config used to override PROMPT_* settings in tests
    without touching env / .env (which load_dotenv override=True would clobber)."""
    def __init__(self, *, mode="text", max_chars=6000):
        self.PROMPT_STORE_MODE = mode
        self.PROMPT_MAX_CHARS = max_chars


def _patch_audit_cfg(mode="text", max_chars=6000):
    """Monkeypatch the Config class imported inside record_llm_call so the
    function reads our test values instead of the real env-derived ones.
    Returns the original Config so callers can restore."""
    import core.app_audit as audit_mod
    import core.app_config as cfg_mod
    fake_cls = lambda mode=mode, mc=max_chars: _FakeCfg(mode=mode, max_chars=mc)
    original = cfg_mod.Config
    cfg_mod.Config = fake_cls
    return original, cfg_mod


def test_record_llm_call_truncates_per_prompt_max_chars():
    from core.app_audit import record_llm_call
    original_cfg, cfg_mod = _patch_audit_cfg(mode="text", max_chars=20)
    try:
        cap = _install_capturing_writer()
        record_llm_call(
            route="r", stage="s", session_id="x", token_id=None,
            prompt="A" * 500, response="B" * 500,
            model="m", latency_ms=1, input_tokens=0, output_tokens=0,
        )
        d = cap.docs[0]
        assert len(d["llm_prompt"]) == 20
        assert d["llm_prompt"].endswith("…")
        assert len(d["llm_output"]) == 20
    finally:
        cfg_mod.Config = original_cfg


def test_record_llm_call_off_mode_strips_bodies():
    from core.app_audit import record_llm_call
    original_cfg, cfg_mod = _patch_audit_cfg(mode="off", max_chars=6000)
    try:
        cap = _install_capturing_writer()
        record_llm_call(
            route="r", stage="s", session_id="x", token_id=None,
            prompt="full prompt", response="full response",
            model="m", latency_ms=1, input_tokens=3, output_tokens=4,
        )
        d = cap.docs[0]
        assert d["llm_prompt"] is None
        assert d["llm_output"] is None
        # metadata still present
        assert d["model"] == "m"
        assert d["input_tokens"] == 3
    finally:
        cfg_mod.Config = original_cfg


def test_audit_llm_call_happy_path_records_message_metadata():
    cap = _install_capturing_writer()
    from core.app_audit import audit_llm_call

    with audit_llm_call(
        route="rt", stage="st",
        session_id="sX", token_id="tX",
        prompt="p",
    ) as ctx:
        msg = _FakeLCNew(11, 22, model="claude-sonnet-4-6")
        ctx.set_response_from_message(msg)
        # Simulate text being extracted by caller
        msg_text = "actual response"
        ctx.response_text = msg_text  # caller can override

    d = cap.docs[0]
    assert d["input_tokens"] == 11
    assert d["output_tokens"] == 22
    assert d["model"] == "claude-sonnet-4-6"
    assert d["llm_output"] == "actual response"
    assert d["latency_ms"] >= 0
    assert d["error"] is None


def test_audit_llm_call_exception_writes_doc_and_reraises():
    cap = _install_capturing_writer()
    from core.app_audit import audit_llm_call

    raised = False
    try:
        with audit_llm_call(
            route="rt", stage="st",
            session_id="sX", token_id=None,
            prompt="p",
        ) as ctx:
            raise RuntimeError("boom from llm")
    except RuntimeError:
        raised = True

    assert raised, "exception must propagate to caller"
    assert len(cap.docs) == 1
    d = cap.docs[0]
    assert d["error"] is not None
    assert "RuntimeError" in d["error"]
    assert "boom from llm" in d["error"]
    assert d["output_tokens"] == 0
    assert d["latency_ms"] >= 0


def test_record_llm_call_swallows_writer_exception():
    """Audit must never raise into the caller, even on writer failure."""
    import core.app_audit as audit_mod

    class _ExplodingWriter:
        def write(self, doc): raise RuntimeError("mongo down")
        def close(self): pass

    audit_mod._writer_instance = _ExplodingWriter()

    from core.app_audit import record_llm_call
    # Must not raise even though writer.write() does.
    record_llm_call(
        route="r", stage="s", session_id="x", token_id=None,
        prompt="p", response="r",
        model="m", latency_ms=1, input_tokens=0, output_tokens=0,
    )


# ===== save_query_recording shim =====

def test_save_query_recording_shim_writes_meeting_event_doc():
    cap = _install_capturing_writer()
    from modules.system_detection.meeting_arrangement.ma_repo import save_query_recording

    save_query_recording(
        session_id="sess-A",
        token_id="tok-A",
        route="meeting_arrangement",
        stage="db_gate_exact",
        question="any free slot?",
        query_dict={"date": "2026-05-08"},
        result_summary={"matched": 2},
        llm_prompt="P",
        llm_output="O",
        extras={"foo": "bar"},
    )
    assert len(cap.docs) == 1
    d = cap.docs[0]
    assert d["sessionId"] == "sess-A"
    assert d["tokenId"] == "tok-A"
    assert d["route"] == "meeting_arrangement"
    assert d["stage"] == "db_gate_exact"
    assert d["kind"] == "meeting_event"
    # legacy fields land in extras
    assert d["extras"]["query"] == {"date": "2026-05-08"}
    assert d["extras"]["result"] == {"matched": 2}
    assert d["extras"]["question"] == "any free slot?"
    assert d["extras"]["foo"] == "bar"
    assert d["llm_prompt"] == "P"
    assert d["llm_output"] == "O"


if __name__ == "__main__":
    # stdlib fallback runner: collect functions named test_* and run them
    import traceback
    failures = 0
    g = dict(globals())
    for name, fn in g.items():
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except Exception:
                failures += 1
                print(f"FAIL  {name}")
                traceback.print_exc()
    sys.exit(1 if failures else 0)
