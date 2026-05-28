# GPU Setup

## Host prerequisites

1. **NVIDIA driver** installed on the host (must match your CUDA runtime — this project uses `cuda:12.1.1`).
2. **NVIDIA Container Toolkit** installed, so Docker can request GPUs via `device_requests`.

```bash
# Verify driver
nvidia-smi

# Verify toolkit
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

If `docker run --gpus all` doesn't produce `nvidia-smi` output, the toolkit
isn't installed or configured.

## How the app picks the device

`core/gpu_config.py` exports two helpers:

### `resolve_device()`

Returns `"cuda"` or `"cpu"` based on:

1. `USE_GPU` — if `false`, always returns `cpu`.
2. `EMBEDDING_DEVICE` — if `cuda` and CUDA is available, returns `cuda`. If `cpu`, returns `cpu`.
3. If `EMBEDDING_DEVICE=auto` (the default) — returns `cuda` when available, otherwise `cpu`.

### `log_gpu_status(logger)`

Logs `{"event": "gpu_status", "device": ..., "cuda_available": ..., "gpu_name": ...}`
once at startup. Also enables TF32 matmul on Ampere-class cards (A6000, A100, etc.):

```python
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True
```

This improves throughput at negligible numerical cost for embeddings.

## Environment variables

| Key | Default | Purpose |
|---|---|---|
| `USE_GPU` | `true` | Master switch. Set to `false` to force CPU for everything. |
| `EMBEDDING_DEVICE` | `auto` | `auto` / `cuda` / `cpu`. `auto` picks CUDA when available. |
| `EMBEDDINGS_PROVIDER` | `openai` | `openai` uses the remote API (no local GPU needed). `hf` uses Sentence-Transformers locally (does use GPU if available). |
| `EMBEDDING_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` | Model when provider=hf. |
| `EMBEDDING_BATCH_SIZE` | `32` | Batch size for HF encoder. |
| `NVIDIA_VISIBLE_DEVICES` | `all` | Passed to Docker / passed through. |
| `NVIDIA_DRIVER_CAPABILITIES` | `compute,utility` | Passed to Docker / passed through. |
| `RAG_GPU_COUNT` | `all` | Count passed to `device_requests.count` in compose. Set to `0` for CPU-only host. |

## docker-compose GPU request

From `docker-compose.yml`:

```yaml
device_requests:
  - driver: nvidia
    count: ${RAG_GPU_COUNT:-0}
    capabilities: ["gpu"]
```

This is the modern docker-compose v3.9 syntax — equivalent to `--gpus all` for
`docker run`. If `RAG_GPU_COUNT` isn't set, compose passes `0`, meaning no GPU.
**So if you forget to set it on a GPU host, the container runs on CPU silently.**

## Modal GPU

`modal_app.py` uses `modal.gpu.L4()` — 1× L4. To switch:

```python
@app.function(
    image=image,
    gpu=modal.gpu.A100(),   # or .A10G(), .T4(), .H100(), etc.
    ...
)
```

Inside the Modal container, defaults are set:

```python
os.environ.setdefault("USE_GPU", "true")
os.environ.setdefault("EMBEDDING_DEVICE", "cuda")
```

## Verifying GPU in a running container

```bash
docker compose exec rag_chatbot python -c "
import torch
print('cuda_available:', torch.cuda.is_available())
print('device_count:', torch.cuda.device_count())
if torch.cuda.is_available():
    print('gpu_name:', torch.cuda.get_device_name(0))
"
```

Or look at the startup log:

```
{"event":"gpu_status","device":"cuda","cuda_available":true,"gpu_name":"NVIDIA A6000"}
```

## CPU fallback

The same app image runs on CPU when:

- `USE_GPU=false`, OR
- CUDA isn't available inside the container, OR
- You built `runtime_cpu` instead of `runtime_cuda`.

Performance caveat: HuggingFace embeddings on CPU are ~10-30× slower. If you
need CPU-only, prefer `EMBEDDINGS_PROVIDER=openai` (remote, same speed either way).

## Troubleshooting

- **"CUDA available = false" inside container** — NVIDIA Container Toolkit isn't installed or `device_requests.count` is `0`. Check `RAG_GPU_COUNT`.
- **`CUDA_VISIBLE_DEVICES=` (empty value) in `.env` silently disables every GPU.** Even with `USE_GPU=true`, an empty string tells the CUDA runtime "no devices visible," so `torch.cuda.is_available()` returns `False` and the code falls back to CPU. Either comment the line out entirely or pin a real index (`CUDA_VISIBLE_DEVICES=0`).
- **Slow embeddings even with GPU** — verify provider: `os.getenv("EMBEDDINGS_PROVIDER")` may still be `openai` (remote). If you set it to `hf`, look for the `embeddings_provider_selected` log emitted at startup — it reports the actual device the HuggingFace encoder was built on (not just `torch.cuda.is_available`).
- **"out of memory" errors** — if CPU OOM at startup, the most likely cause is silent CPU fallback while `EMBEDDINGS_PROVIDER=hf`: every embed call (build + bootstrap + redundancy filter) runs in RAM. Fix GPU passthrough first (`RAG_GPU_COUNT`, empty `CUDA_VISIBLE_DEVICES`), then verify with the `embeddings_provider_selected` log. If GPU OOM: reduce `EMBEDDING_BATCH_SIZE` (default 32). For an L4, 16 is safer.

## Confirming the embedding device at runtime

`embeddings_provider_selected` is logged once per `_build_embeddings()` call (i.e. at bootstrap and on each `/knowledgebase-rebuild`). Grep for it:

```bash
docker compose logs rag_chatbot | grep embeddings_provider_selected
# {"event":"embeddings_provider_selected","provider":"hf","model":"sentence-transformers/all-MiniLM-L6-v2","device":"cuda","batch_size":32,"caller":"sd_vector_legacy"}
```

If `device` is `cpu` while `USE_GPU=true` and `EMBEDDING_DEVICE=cuda`, the container did NOT receive a GPU — check `RAG_GPU_COUNT`, `NVIDIA_VISIBLE_DEVICES`, and `CUDA_VISIBLE_DEVICES` in that order.

See [`troubleshooting.md`](troubleshooting.md) for more.
