from __future__ import annotations

import json
from typing import Dict, Any, Tuple, Union
from .tg_repo import TokenRepo
from .tg_utils import getenv_str


class TokenService:
    def __init__(self, repo: TokenRepo) -> None:
        self.repo = repo
        self.trigger_value = getenv_str("TRIGGER_TRUE_VALUE", "true")  # dipakai endpoint #2
        self.env_api_key_default = getenv_str("API_KEY", "")

    # -------- API KEY (now accepts websiteId + api_key) --------
    def generate_api_key(self, data: Union[Dict[str, Any], str]) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        """
        Expect JSON: {"websiteId": "<string>", "api_key": "<string>"}
        - Jika "api_key" tidak di-body, akan fallback ke env API_KEY (jika tersedia).
        """
        # Normalisasi payload ke dict
        if isinstance(data, dict):
            payload = data
        else:
            raw = (data or "")
            payload = None
            try:
                payload = json.loads(raw)
            except Exception:
                try:
                    payload = json.loads(raw.lstrip("\ufeff").strip())
                except Exception:
                    payload = None

        if not isinstance(payload, dict):
            return {"error": 'Invalid body. Send JSON: {"websiteId": "<string>", "api_key": "<string>"}.'}

        websiteId = str(payload.get("websiteId", "")).strip()
        api_key_in  = str(payload.get("api_key", "")).strip()
        name_in    = str(payload.get("name", "")).strip()

        if not websiteId:
            return {"error": "websiteId is required."}

        api_key = api_key_in or self.env_api_key_default
        if not api_key:
            return {"error": "api_key is required (in body or set API_KEY in environment)."}

        out = self.repo.generate_api_key(websiteId=websiteId, api_key=api_key, name=name_in)   # << pass name
        return {
            "status": "ok",
            "websiteId": out.get("websiteId"),
            "api_key": out.get("api_key"),
            "name": out.get("name"),                                
            "userId": out["userId"],
            "user_id_generated_at": out["user_id_generated_at"],
        }

    # -------- SESSION TOKEN (tetap sama) --------
    def generate_session_id(self, raw_body: str, key_header_value: str | None):
        if raw_body.strip().lower() != self.trigger_value:
            return {"error": f"Invalid trigger body. Expecting plain-text '{self.trigger_value}'."}
        if not key_header_value:
            return {"error": f"Missing {self.repo.api_header_name} header."}

        # ⬇️ gunakan EFFECTIVE ACTIVE check (bukan $elemMatch status:active mentah)
        if self.repo.has_active_session(key_header_value):
            return ({"error": "Active token exists. Deactivate it first (auto via scheduler) or wait."}, 409)

        rec = self.repo.append_active_token(key_header_value)
        return {"status": "ok", "tokenId": rec["tokenId"], "token_generated_at": rec["token_generated_at"]}