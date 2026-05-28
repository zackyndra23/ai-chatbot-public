from typing import List, Dict
from .cwh_utils import clamp_messages_to_budget, pair_qas_from_tail, render_history_block
from core.app_config import Config
cfg = Config()

def _base_system_guard() -> Dict[str, str]:
    return {"role": "system", "content":
            "You are the company chatbot. Follow policy, keep PII masked."}

def _summary_block(summary: str) -> Dict[str, str]:
    return {"role": "system", "content": f"{summary}"} if summary else None

def _tail_to_messages(tail: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out = []
    for t in tail:
        if t["role"] in ("user", "assistant"):
            out.append({"role": t["role"], "content": t["content"]})
    return out

# --- helper to attach history block as a system message ---
def _history_block_message(tail_msgs: List[Dict[str, str]]) -> Dict[str, str] | None:
    pairs = pair_qas_from_tail(tail_msgs)
    if not pairs:
        return None
    block = render_history_block(pairs)
    return {"role": "system", "content": block}

def build_messages_for_sd(window, user_now: str, task_instr: str,
                          tokens_budget: int = None,
                          include_history_block: bool = True):
    tokens_budget = tokens_budget or cfg.INPUT_MAX_PROMPT
    messages = []
    messages.append(_base_system_guard())
    sb = _summary_block(window.get("summary", ""))
    if sb: messages.append(sb)

    tail_msgs = _tail_to_messages(window.get("tail", []))
    if include_history_block:
        hb = _history_block_message(tail_msgs)
        if hb: messages.append(hb)

    messages += tail_msgs
    messages.append({"role": "user", "content": user_now})
    messages.append({"role": "system", "content": task_instr})
    messages, truncated = clamp_messages_to_budget(messages, tokens_budget)
    return {"messages": messages, "used_history_turns": len(window.get("tail", [])), "truncated": truncated}

def build_messages_for_ma(window, user_now: str, meeting_instr: str,
                          tokens_budget: int = None,
                          include_history_block: bool = True):
    return build_messages_for_sd(window, user_now, meeting_instr,
                                 tokens_budget=tokens_budget,
                                 include_history_block=include_history_block)

def format_chat_history_block(pairs: List[Dict[str, str]]) -> str:
    """
    pairs: list of {"question": "...", "message": "..."} (urutan lama -> baru)
    """
    if not pairs:
        return "Chat History:\n(Not exist yet)"
    lines = ["Chat History:"]
    for i, p in enumerate(pairs, start=1):
        idx = f"{i:02d}"
        q = (p.get("question") or "").strip()
        m = (p.get("message") or "").strip()
        lines.append(f"question{idx}: {q}")
        lines.append(f"message{idx}: {m}")
    return "\n".join(lines)

def build_history_summarize_prompt(
    pairs: List[Dict[str, str]],
    max_chars: int = 1200,
    language_name: str | None = None
) -> str:
    """
    Prompt LLM khusus untuk merangkum seluruh percakapan menjadi ringkasan kaya konteks,
    faktual, dan netral bahasa (menyesuaikan dengan bahasa dominan user).
    Ringkasan ini akan digunakan sebagai long-term memory untuk menyambung percakapan berikutnya.
    """
    lines = []
    for i, p in enumerate(pairs, start=1):
        q = p.get("question", "").replace("\n", " ").strip()
        a = p.get("message", "").replace("\n", " ").strip()
        lines.append(f"Q{i}: {q}")
        lines.append(f"A{i}: {a}")
    qa_dump = "\n".join(lines)

    # Jika tidak diberikan, fallback ke rule lama
    if not language_name:
        language_instruction = (
            "Use the same language as the last user question in the dialog below. "
            "Do NOT switch languages. Output must strictly follow that language."
        )
    else:
        language_instruction = (
            f"Write the entire summary STRICTLY in {language_name}. "
            f"Do NOT switch languages. Do NOT use English unless {language_name} is English."
        )

    return (
        "You are a careful summarizer for a multilingual customer-service chatbot. "
        "Read the full conversation pairs (Q/A) below and "
        "produce a comprehensive yet concise summary that captures:\n"
        "- The topic of the conversation\n"
        "- Important facts, user needs, or context shared\n"
        "- Key answers or information provided by the assistant\n"
        "- Any open questions, next actions, or follow-up points\n"
        f"{language_instruction}\n"
        f"Target maximum length: around {max_chars} characters. Write in 1–3 short paragraphs, "
        "or up to 10 bullet points. Avoid hallucinations.\n\n"
        "Output requirements:\n"
        "- Keep it factual and descriptive (no greetings, no conclusions)\n"
        "- Preserve proper names, organizations, dates, or commitments mentioned\n"
        "- If the user discussed scheduling a meeting or service interest, include that context explicitly\n"
        "- The summary should help the assistant recall what has happened in this chat later on\n\n"
        "=== FULL DIALOG ===\n"
        f"{qa_dump}\n"
        "=== END ===\n\n"
        "Now write the summary:"
    )

def format_chat_summarization_block(summary_text: str) -> str:
    """
    Formatkan blok 'Chat Summarization'. Jika belum ada ringkasan (atau belum ada percakapan),
    tetap tampilkan header dengan '(Not exist yet)' agar konsisten dengan Chat History.
    """
    text = (summary_text or "").strip()
    if not text:
        return "Chat Summarization:\n(Not exist yet)"
    return f"Chat Summarization:\n{text}"