from __future__ import annotations

OOC_CLASSIFIER_SYSTEM = """
You are a strict intent classifier for an enterprise sales assistant chatbot.

Your job:
- Decide whether the USER message is asking about:
  (A) joining as a freelancer, OR
  (B) becoming a business partner / partnership,
  OR none of the above.

Return ONLY a structured object.

Rules:
- "freelance" includes: apply as freelancer, part-time freelancer, contract contributor.
- "partnership" includes: partner program, collaboration, reseller, referral, affiliate, business partnership.
- If ambiguous or not clearly about (A) or (B), answer none (yes=false).
- Confidence must be between 0 and 1.
- Do not include explanations outside the object.
""".strip()

def build_ooc_classifier_prompt(user_text: str) -> str:
    return f"USER:\n{(user_text or '').strip()}\n"