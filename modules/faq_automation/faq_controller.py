from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/aitegrity-core", tags=["faq"])

@router.post("/faq-automation")
async def ingest(request: Request):
    cfg = request.app.state.cfg
    api_key = request.headers.get(cfg.API_HEADER_NAME, "")
    if not api_key or api_key != cfg.API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    faq_verificator = (getattr(cfg, "FAQ_VERIFICATOR", "on") or "on").strip().lower()
    if faq_verificator not in ("on", "true", "1", "yes"):
        return JSONResponse(
            {"ok": False, "reason": "FAQ_VERIFICATOR is disabled"},
            status_code=400
        )

    ctype = (request.headers.get("content-type") or "").lower()
    if "text/plain" not in ctype:
        raise HTTPException(status_code=415, detail="Content-Type must be text/plain")

    body = (await request.body()).decode("utf-8", errors="ignore").strip().lower()
    if body != cfg.TRIGGER_TRUE_VALUE:
        return JSONResponse(
            {"ok": False, "reason": f"payload must be '{cfg.TRIGGER_TRUE_VALUE}'"},
            status_code=400
        )

    # === Sumber URL dinamis ===
    # Jika PUBLIC_BASE_URL diset (mis. "https://api.integrity-asia.com:2303"),
    # pakai itu; kalau tidak, pakai URL dari request (host/ip saat ini).
    if getattr(cfg, "PUBLIC_BASE_URL", None):
        source_url = cfg.PUBLIC_BASE_URL.rstrip("/") + request.url.path
    else:
        source_url = str(request.url)

    svc = request.app.state.services.faq
    out = svc.run_pipeline(source=source_url)
    return JSONResponse({"ok": True, **out})
