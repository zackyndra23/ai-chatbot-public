import os

def resolve_device() -> str:
    want = (os.getenv("EMBEDDING_DEVICE") or "auto").strip().lower()
    use_gpu = (os.getenv("USE_GPU", "true").strip().lower() in ("1", "true", "yes", "on"))

    if not use_gpu:
        return "cpu"

    try:
        import torch
        cuda_ok = torch.cuda.is_available()
    except Exception:
        cuda_ok = False

    if want == "cuda":
        return "cuda" if cuda_ok else "cpu"
    if want == "cpu":
        return "cpu"

    # auto
    return "cuda" if cuda_ok else "cpu"

def log_gpu_status(logger=None) -> dict:
    info = {"device": "cpu", "cuda_available": False, "gpu_name": None}
    try:
        import torch
        info["cuda_available"] = bool(torch.cuda.is_available())
        info["device"] = resolve_device()
        if info["cuda_available"]:
            info["gpu_name"] = torch.cuda.get_device_name(0)
            # Opsional: TF32 for Ampere (A6000)
            try:
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
            except Exception:
                pass
    except Exception:
        pass

    if logger:
        logger.info({"event": "gpu_status", **info})
    return info