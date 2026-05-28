from types import SimpleNamespace
from .sa_repo import ServiceAgentRepo
from modules.service_agent.sa_flows import FLOW_REGISTRY
from .sa_types import AgentSessionState
from .sa_dto import CrispPickerMessage, CrispPickerChoice, CrispPickerContent
from . import sa_policies
import json
import time
import uuid
from infra.app_repo import get_mongo_client
from langchain_anthropic import ChatAnthropic
# from langchain_core.messages import SystemMessage, HumanMessage
from .sa_prompts import SA_SUMMARY_PROMPT
from modules.system_detection.sd_policies import build_language_meta
from modules.service_agent import sa_policies as SA_POL
from modules.chat_payload.payload_builder import build_string_message
from modules.system_detection.sd_repo import (
    read_user_nick_from_sessions,
    ensure_user_nick_in_sessions,
)

from core.app_config import Config
cfg = Config()

class INTAgentService:
    def __init__(self, repo: ServiceAgentRepo, llm_client):
        self.repo = repo
        self.llm = llm_client

    def _build_answers_skeleton(self, flow: dict) -> dict:
        """
        Buat semua key jawaban dari flow (field_name) dan isi default "".
        Tidak nambah per step; langsung lengkap dari awal.
        """
        answers = {}
        for step in flow.values():
            if getattr(step, "is_question", True) and getattr(step, "field_name", None):
                answers[step.field_name] = ""
        return answers

    def _get_first_step(self, flow: dict):
        """
        Ambil step pertama dari sebuah flow.
        Rule: step dengan order terkecil (default besar kalau tidak ada order).
        """
        steps = list(flow.values())
        if not steps:
            raise ValueError("Flow is empty")

        def _order(s):
            try:
                return int(getattr(s, "order", 10**9) or 10**9)
            except Exception:
                return 10**9

        steps_sorted = sorted(steps, key=_order)
        return steps_sorted[0]

    def start_flow(
        self,
        session_id: str,
        service_code: str,
        service_label: str = "",
        language_code: str = "",
        language_name: str = "",
    ) -> CrispPickerMessage:
        flow = FLOW_REGISTRY[service_code]
        first_step = self._get_first_step(flow)

        answers = self._build_answers_skeleton(flow)

        # fallback aman: jangan pernah biarkan kosong
        lc = (language_code or "").strip().lower()
        ln = (language_name or "").strip()

        if not lc and ln:
            low = ln.lower()
            if "english" in low:
                lc = "en"
            elif "indo" in low:
                lc = "id"

        if not lc:
            lc = "en"
        if not ln:
            ln = "English" if lc == "en" else "Indonesia"

        state = AgentSessionState(
            session_id=session_id,
            service_code=service_code,
            service_label=service_label or getattr(first_step, "service_label", "") or service_code,
            question_id=first_step.id,
            answers=answers,
            status=f"ongoing on {first_step.id}",
            language_code=lc,
            language_name=ln,
        )
        self.repo.upsert_state(state)
        return self._build_crisp_message_from_step(first_step)

    # reset_session removed — Crisp handles "start a new chat" natively.

    def _build_completion_payload(self, state: AgentSessionState) -> dict:
        """
        Payload ketika flow selesai (completed).
        SD akan pakai ini untuk render final closing message.
        """
        service_value_code = (state.service_code or "").strip()

        lc = (getattr(state, "language_code", "") or "").strip().lower()
        ln = (getattr(state, "language_name", "") or "").strip()

        if not lc and ln:
            low = ln.lower()
            if "english" in low:
                lc = "en"
            elif "indo" in low:
                lc = "id"

        if not lc:
            lc = "en"
        if not ln:
            ln = "English" if lc == "en" else "Indonesia"

        return {
            "route": f"agent_service_{service_value_code.lower()}",
            "service_value_code": service_value_code,
            "service_code": state.service_code,
            "service_label": state.service_label,
            "language_code": lc,
            "language_name": ln,
            "status": "completed",
            "extra": {
                "service_code": state.service_code,
                "service_label": state.service_label,
                "answers": state.answers,
                "status": "completed",
            },
        }

    # 2) handle picker reply
    def handle_picker_reply(self, reply) -> CrispPickerMessage | dict:
        state = self.repo.get_state(reply.session_id)
        flow = FLOW_REGISTRY[state.service_code]
        step = flow[state.question_id]

        # simpan jawaban
        key = step.field_name or step.id
        state.answers[key] = reply.value

        # hitung next
        next_id = step.next_if.get(reply.value, step.default_next)
        if next_id is None or next_id.startswith("route_"):
            # selesai / route ke service lain
            state.status = "completed"
            self.repo.upsert_state(state)
            return self._build_completion_payload(state)

        state.question_id = next_id
        self.repo.upsert_state(state)
        next_step = flow[next_id]
        return self._build_crisp_message_from_step(next_step)

    # helper bikin Crisp message dari QuestionStep
    def _build_crisp_message_from_step(self, step):
        choices = []
        if step.choices:
            choices = [
                CrispPickerChoice(
                    value=c.value,
                    label=c.label,
                    selected=c.selected
                )
                for c in step.choices
            ]

        content = CrispPickerContent(
            id=step.id,
            text=step.text,
            choices=choices
        )
        return CrispPickerMessage(content=content)
    
    def _init_answers_template(self, flow: dict) -> dict:
        """
        Prefill semua field jawaban berdasarkan flow.
        Key = step.field_name (kalau ada) else step.id.
        Default value = "" (kosong).
        Hanya untuk step yang is_question=True.
        """
        template: dict = {}
        for step_id, step in flow.items():
            if not getattr(step, "is_question", True):
                continue
            key = getattr(step, "field_name", None) or step_id
            # prefill kosong dulu
            template[key] = ""
        return template

    def get_current_step_bundle(self, session_id: str) -> dict:
        state = self.repo.get_state(session_id)
        if not state:
            return {"ok": False, "error": "no_state"}

        flow = FLOW_REGISTRY[state.service_code]
        step = flow[state.question_id]

        extra = {
            "service_code": state.service_code,
            "service_label": state.service_label,
            "answers": state.answers,
            "status": state.status,
            "dual_agent_meta": getattr(state, "dual_agent_meta", {}) or {},
        }

        return {
            "ok": True,
            "state": state,
            "current_step": step,
            "extra": extra,
        }

    @staticmethod
    def _append_answer_slot(prev_val, new_text: str):
        """
        Return value yang menyimpan multi-answer:
        - "" -> "text"
        - "old" -> {"answer_01": "old", "answer_02": "new"}
        - {"answer_01":. .} -> tambah answer_N berikutnya
        """
        new_text = (new_text or "").strip()

        if prev_val is None or prev_val == "":
            return new_text

        if isinstance(prev_val, str):
            old = prev_val.strip()
            if old == "":
                return new_text
            return {"answer_01": old, "answer_02": new_text}

        if isinstance(prev_val, dict):
            i = 1
            while f"answer_{i:02d}" in prev_val:
                i += 1
            prev_val[f"answer_{i:02d}"] = new_text
            return prev_val

        return new_text

    def commit_turn(self, session_id: str, user_answer: str, extra: dict, advance: bool) -> dict:
        state = self.repo.get_state(session_id)
        if not state:
            return {"ok": False, "error": "no_state"}

        flow = FLOW_REGISTRY[state.service_code]
        step = flow[state.question_id]

        # simpan jawaban ke field current (support multi-answer)
        key = step.field_name or step.id
        clean_answer = (user_answer or "").strip()

        # simpan dual_agent_meta ke state (persist)
        dam = (extra or {}).get("dual_agent_meta") or {}
        state.dual_agent_meta = dam

        # 2026-05-08 junk-data guard: only write `answers[key]` when classifier
        # confirms the user actually gave an answer to the qualification question.
        # When type=question_only the user is asking (e.g. cross-service info),
        # not answering — pre-fix this polluted leads with text like
        # `wbs_user_eligibility: "saya juga tertarik dengan EBS..."`.
        # Anti-loop force-advance behavior is unchanged (still controlled upstream
        # by dual_agent_meta.next_question); we just skip committing junk.
        classifier_type = (dam.get("type") or "").strip().lower()
        is_real_answer = classifier_type in ("answer_only", "answer_and_question")

        if is_real_answer and clean_answer:
            prev_val = state.answers.get(key, "")
            state.answers[key] = self._append_answer_slot(prev_val, clean_answer)

        prev_step_text = step.text
        next_step_text = step.text  # default stay

        if advance:
            # hitung next
            next_id = step.default_next
            if step.next_if:
                next_id = step.next_if.get(clean_answer, step.default_next)

            # kalau selesai / route
            if next_id is None or (isinstance(next_id, str) and next_id.startswith("route_")):
                state.status = "completed"
                self.repo.upsert_state(state)
                return {"ok": True, "status": "completed", "state": state, "prev_step_text": prev_step_text, "next_step_text": "-"}

            # advance
            state.question_id = next_id
            state.status = f"ongoing on {next_id}"
            next_step_text = flow[next_id].text

        else:
            # stay
            state.status = f"ongoing on {state.question_id}"

        self.repo.upsert_state(state)

        return {
            "ok": True,
            "status": state.status,
            "state": state,
            "prev_step_text": prev_step_text,
            "next_step_text": next_step_text,
            "extra": {
                "service_code": state.service_code,
                "service_label": state.service_label,
                "answers": state.answers,
                "status": state.status,
                "dual_agent_meta": state.dual_agent_meta,
            }
        }

    def handle_from_question(self, session_id: str, question: str, token_id: str | None = None, handoff_bundle: dict | None = None) -> dict:
        # RESOLVE NICKNAME — satu-satunya sumber: crisp_sessions
        resolved_nick = read_user_nick_from_sessions(session_id)  # bisa None jika belum diset

        # (opsional) simpan ke chat_history/ run_logs agar mudah dilihat di log
        if resolved_nick:
            ensure_user_nick_in_sessions(session_id, resolved_nick)  # tidak mengubah crisp_sessions

        # 1) Language meta (deterministic, no LLM)
        language_code, language_name = build_language_meta(question)

        q = (question or "").strip()

        # 1) START dari SA_SELECT_<service_value_code>
        if q.startswith(SA_POL.SERVICE_AGENT_PREFIX):
            service_value_code = q[len(SA_POL.SERVICE_AGENT_PREFIX):].strip()
            flow_code = SA_POL.SERVICE_CODE_TO_FLOW_CODE.get(service_value_code)
            if not flow_code:
                return {
                    "route": "service_agent_error",
                    "service_value_code": service_value_code,
                    "extra": {"error": "unknown_service_value_code", "value": service_value_code},
                }

            service_label = SA_POL.SERVICE_LABEL_CODE_MAP.get(service_value_code, service_value_code)

            # start flow -> upsert state + prefill answers
            self.start_flow(
                session_id=session_id,
                service_code=flow_code,
                service_label=service_label,
                language_code=(handoff_bundle or {}).get("language_code", ""),
                language_name=(handoff_bundle or {}).get("language_name", ""),
            )

            state = self.repo.get_state(session_id)
            flow = FLOW_REGISTRY[state.service_code]
            step = flow[state.question_id]  # first step

            return {
                "route": f"agent_service_{service_value_code}",
                "service_value_code": service_value_code,
                "service_code": state.service_code,
                "service_label": state.service_label,
                "step_id": step.id,
                "step_text": step.text,  # seed pertanyaan pertama (buat SD render "Next Qualification Question")
                "extra": {
                    "service_code": state.service_code,
                    "service_label": state.service_label,
                    "answers": state.answers,
                    "status": state.status,
                },
            }

        # 2) ONGOING: jangan advance di sini (SD yang decide stay/advance via commit_turn)
        state = self.repo.get_state(session_id)
        if not state:
            err_text = (
                "Sesi kualifikasi belum dimulai."
                if (language_code or "").lower().startswith("id")
                else "The qualification session has not started yet."
            )
            return {
                "route": "service_agent_error",
                "message": self.build_sd_string_message(err_text),
                "extra": {"error": "no_state"},
            }

        flow = FLOW_REGISTRY[state.service_code]
        step = flow[state.question_id]

        # peek next step (tanpa mengubah state)
        next_id = getattr(step, "default_next", None)
        if getattr(step, "next_if", None):
            # NOTE: di sini kita belum commit jawaban, jadi next_if tidak dipakai untuk routing.
            # next_if hanya akan dipakai saat commit_turn(advance=True) kalau memang kamu butuh.
            pass

        next_q_text = ""
        if next_id and isinstance(next_id, str) and next_id in flow:
            next_q_text = getattr(flow[next_id], "text", "") or ""

        # return bundle untuk SD render + dual-agent
        bundle = self.get_current_step_bundle(session_id)

        state_language_code = (getattr(state, "language_code", "") or "").strip()
        state_language_name = (getattr(state, "language_name", "") or "").strip()

        if not state_language_code and state_language_name:
            low = state_language_name.lower()
            if "english" in low:
                state_language_code = "en"
            elif "indo" in low:
                state_language_code = "id"

        return {
            "route": f"agent_service_{state.service_code.lower()}",
            "language_code": state_language_code,
            "language_name": state_language_name,
            "service_code": state.service_code,
            "service_label": state.service_label,
            "sa_mode": "ongoing",
            "current_question_id": state.question_id,
            "current_question_text": getattr(step, "text", "") or "",
            "next_question_id": next_id or "",
            "next_question_text": next_q_text,
            "extra": bundle.get("extra") or {
                "service_code": state.service_code,
                "service_label": state.service_label,
                "answers": state.answers,
                "status": state.status,
                "dual_agent_meta": getattr(state, "dual_agent_meta", {}) or {},
            },
        }

    def _parse_sa_select_value(raw: str) -> str:
        raw = (raw or "").strip()
        if raw.startswith(SA_POL.SERVICE_AGENT_PREFIX):
            return raw[len(SA_POL.SERVICE_AGENT_PREFIX):]
        return raw

    def build_sd_string_message(self, text: str, msg_id: str | None = None) -> dict:
        return {
            "type": "string",
            "content": {
                "id": msg_id or f"q-{uuid.uuid4().hex[:8]}",
                "text": text,
                "choices": None,
                "required": None,
            }
        }

    def _build_global_service_picker(self, language_code: str | None = None) -> dict:
        """
        Kalau user klik 'More Services' di tengah-tengah,
        sementara balikin text biasa dahulu.
        """
        text = (
            "Silakan tuliskan layanan lain yang ingin Anda diskusikan."
            if (language_code or "").lower().startswith("id")
            else "Please type the other service you would like to discuss."
        )

        return {
            "message": {
                "type": "text",
                "content": {
                    "text": text
                }
            }
        }
    
    def _build_blank_answers(self, service_code: str) -> dict:
        flow = FLOW_REGISTRY[service_code]
        out = {}
        for step_id, step in flow.items():
            if getattr(step, "field_name", None):
                out[step.field_name] = ""
        return out


    def start_flow_for_sd(self, session_id: str, service_code: str, token_id: str | None = None) -> dict:
        # start flow => persist state + answers skeleton
        _ = self.start_flow(session_id=session_id, service_code=service_code)

        state = self.repo.get_state(session_id)
        if state is None:
            raise ValueError(f"SA state not found after start_flow: session_id={session_id}")

        # ambil step pertama dari state
        flow = FLOW_REGISTRY[service_code]
        first_step = flow[state.question_id]  # question_id sudah first_step.id

        # ✅ status harus step_id (state.status), bukan seed text
        extra = {
            "answers": state.answers,
            "service_code": state.service_code,
            "service_label": state.service_label,
            "status": state.status,
            # optional kalau kamu mau simpan juga:
            # "service_value_code": SA_POL.FLOW_CODE_TO_SERVICE_VALUE_CODE.get(service_code),
        }

        # ✅ message harus string (bukan picker), dan id “m-xxxx” seperti mode multi
        msg_dict = build_string_message(first_step.text)

        return {
            "service_code": state.service_code,
            "service_label": state.service_label,
            "message": msg_dict,
            "extra": extra,
            "route": f"agent_service_{service_code.lower()}",
        }

    def get_first_question_seed(self, service_code: str) -> dict:
        flow = FLOW_REGISTRY[service_code]
        # pilih step dengan order terkecil yang is_question=True
        steps = [s for s in flow.values() if getattr(s, "is_question", True)]
        steps.sort(key=lambda s: getattr(s, "order", 999))
        s0 = steps[0]

        return {
            "service": service_code,
            "order": int(getattr(s0, "order", 1)),
            "seed": str(getattr(s0, "text", "")).strip(),
        }

# ==== global wiring SA_ENGINE  ====

SA_LLM = ChatAnthropic(
    model=cfg.ANTHROPIC_MODEL,
    anthropic_api_key=cfg.ANTHROPIC_API_KEY,
    max_tokens=cfg.MAX_TOKENS_ASK,
    temperature=cfg.LLM_TEMPERATURE,
)

_sa_repo = ServiceAgentRepo(get_mongo_client())
SA_ENGINE = INTAgentService(repo=_sa_repo, llm_client=SA_LLM)