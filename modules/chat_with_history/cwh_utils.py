from typing import List, Dict

def mask_text(s: str) -> str:
    return s  # sementara: tidak melakukan masking

def maybe_mask(s: str, store_raw: bool, store_masked: bool) -> str:
    return s  # paksa non-masking sampai integrasi siap

def clamp_messages_to_budget(messages: list, budget_tokens: int) -> tuple[list, bool]:
    # Implementasi ringan: potong dari history paling awal jika panjang.
    # (Atau hitung token beneran kalau kamu punya tokenizer)
    truncated = False
    if len(messages) > 512:  # placeholder safeguard
        messages = messages[-512:]
        truncated = True
    return messages, truncated

# --- pair up user/assistant into questionN/messageN and render a block ---

def pair_qas_from_tail(tail: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Input: [{'role':'user'|'assistant','content':...}, ...] (chronological)
    Output: [{'question': '...','message':'...'}, ...] paired in order.
    """
    pairs = []
    cur_q = None
    for m in tail:
        r = (m.get("role") or "").lower()
        c = (m.get("content") or "").strip()
        if not c:
            continue
        if r == "user":
            # close previous incomplete question with empty answer
            if cur_q is not None:
                pairs.append({"question": cur_q, "message": ""})
            cur_q = c
        elif r == "assistant":
            if cur_q is None:
                # assistant with no question before -> treat as standalone
                pairs.append({"question": "", "message": c})
            else:
                pairs.append({"question": cur_q, "message": c})
                cur_q = None
    if cur_q is not None:
        pairs.append({"question": cur_q, "message": ""})
    return pairs

def render_history_block(pairs: List[Dict[str, str]], max_chars: int = 3000) -> str:
    """
    Render as:
    Chat history:
    question1: ...
    message1: ...
    question2: ...
    message2: ...
    """
    lines = ["Chat history:"]
    for i, p in enumerate(pairs, 1):
        q = (p.get("question") or "").strip()
        a = (p.get("message") or "").strip()
        if q:
            lines.append(f"question{i}: {q}")
        if a:
            lines.append(f"message{i}: {a}")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else (text[:max_chars] + "…")