# Moondream2 Vision Worker — Node Spec

> **Superseded:** the agent no longer consumes a worker directly. The public
> contract is now the **vision.ffilt.us capability API**
> (`SPEC-VISION-API.md` in the `reeds/vision` repo). This document is a
> *backing-provider runbook* for one way the vision service can serve
> Moondream2 (llama.cpp + Vulkan on this RX 470 box); the service adapts it
> behind `/v1/describe`, `/v1/kind`, `/v1/query`, `/v1/detect`.

The vision service needs a Moondream2 vision-language backend (image
captions + UI-element classification). This spec is what the worker
node must provide so the vision service can rely on it.

Status: **proposed** — worker not yet deployed. Until it is, the agent falls
back to OCR-only perception (`Perception.error` set).

## 1. Capability contract

The worker is a **Moondream2** vision-language server behind an OpenAI-compatible
HTTP API. It must expose:

| Capability | Method | Shape |
|---|---|---|
| Models list | `GET /v1/models` | `{"object":"list","data":[{"id":"moondream2",...}]}` |
| Image caption / Q&A | `POST /v1/chat/completions` | image as `image_url` data URI |

It does NOT need: embeddings, audio, tool calls, streaming (optional). One
model is enough (`moondream2`).

### Request the agent sends

```json
{
  "model": "moondream2",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "What kind of user-interface element is this? Answer with exactly one word: button, link, input field, image, other."},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR..."}}
    ]
  }],
  "temperature": 0.1,
  "max_tokens": 64
}
```

### Response the agent parses

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "moondream2",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "button"},
    "finish_reason": "stop"
  }]
}
```

### Endpoint env (what the agent uses)

- `VISION_BASE` — worker base URL, e.g. `http://<worker>:8080`
- `VISION_MODEL` — model id to request, default `moondream2`
- Optional `VISION_API_KEY` — if the worker requires auth

The agent's `vision/ml.py` exposes `RemoteModel` that implements the same
interface as the local `Model` (`describe`, `kind`, `query`, `detect`),
selected automatically when `VISION_BASE` is set.

## 2. Worker requirements

### Recommended: AMD GPU worker (llama.cpp + Vulkan)

- **GPU**: AMD Polaris or newer with Vulkan 1.1+ (RX 470/580 = 4–8GB VRAM,
  verified working here). RADV/Mesa driver.
- **VRAM**: Moondream2 text `Q4_K_M` (~1.4GB) + mmproj F16 (~0.9GB) +
  KV cache fits in **4GB**; more is better for `--n-gpu-layers`.
- **CPU**: 4+ cores (vision encoder runs on CPU in this stack unless offloaded).
- **RAM**: ≥ 4GB free.
- **OS**: Linux (Manjaro/Arch verified). Vulkan ICD present (`vulkaninfo`
  shows `RADV POLARIS10`).
- **Disk**: ≥ 5GB for GGUF files.

### Minimal CPU-only fallback worker

- 4 cores, 6GB free RAM, no GPU. Same software, `--n-gpu-layers 0`.
- Slower (seconds per caption) but functional.

## 3. Software / deploy

### Option A — llama.cpp server (recommended)

```bash
# build with Vulkan
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build -j --config Release --target llama-server llama-quantize
```

```bash
# fetch GGUFs (official repo)
huggingface-cli download moondream/moondream2-gguf \
  moondream2-text-model-f16.gguf --local-dir /srv/models/moondream2
huggingface-cli download moondream/moondream2-gguf \
  moondream2-mmproj-f16.gguf --local-dir /srv/models/moondream2
```

Optional: quantize text model to Q4 for 4GB VRAM:

```bash
./build/bin/llama-quantize /srv/models/moondream2/moondream2-text-model-f16.gguf \
  /srv/models/moondream2/moondream2-text-model-Q4_K_M.gguf Q4_K_M
```

```bash
# serve OpenAI-compatible API on the LAN
./build/bin/llama-server \
  --model /srv/models/moondream2/moondream2-text-model-Q4_K_M.gguf \
  --mmproj  /srv/models/moondream2/moondream2-mmproj-f16.gguf \
  --host 0.0.0.0 --port 8080 \
  --n-gpu-layers 99 --ctx-size 4096 \
  --alias moondream2 \
  --temp 0.1
```

Expected startup log: `device: Vulkan0 (AMD Radeon RX 470 Graphics)`.

### Option B — k3s pod

Wrap Option A in a Deployment exposing port 8080. Suggested image base:
`alpine`/`archlinux` + the llama-server binary + GGUF files on a volume.
Set env `VISION_BASE` on the agent accordingly.

### Smoke test (from the agent host)

```bash
# 1. models
curl -s http://<worker>:8080/v1/models | head

# 2. caption a screenshot
IMG=$(base64 -w0 /tmp/shot.png)
curl -s http://<worker>:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"moondream2\",\"messages\":[{\"role\":\"user\",\"content\":[
        {\"type\":\"text\",\"text\":\"Describe this screen.\"},
        {\"type\":\"image_url\",\"image_url\":{\"url\":\"data:image/png;base64,$IMG\"}}]}],
       \"temperature\":0.1,\"max_tokens\":128}"
```

## 4. Agent-side integration

`vision/ml.py` gains a `RemoteModel` (used when `VISION_BASE` is set):

```python
from vision import ml
m = ml.get_model()          # RemoteModel if VISION_BASE set, else local
m.describe(pil_img)         # -> "A login form with username and password fields"
m.kind(pil_crop, text="")   # -> "button" | "link" | "input" | "image" | "unknown"
```

- Same best-effort guarantee: if the worker is unreachable, `get_model()`
  returns `None` and OCR-only perception is used.
- Same `KINDS` vocabulary as the local path so the agent is backend-agnostic.
- Bounded latency: agent `perceive(max_ml_targets=N)` caps remote classify
  calls per screenshot.

## 5. Requirements matrix

| Item | Requirement | Verified on this box |
|---|---|---|
| GPU (recommended) | AMD Vulkan 1.1+, ≥4GB VRAM | RX 470, RADV, Vulkan 1.4 ✓ |
| CPU | 4+ cores | Ryzen 5 2600 (12 threads) ✓ |
| RAM | ≥4GB free | ~6GB available ✓ |
| Disk | ≥5GB free | ✓ |
| OS | Linux | Manjaro ✓ |
| llama.cpp | GGML_VULKAN=ON build | pending |
| Models | moondream2 text + mmproj GGUF | pending |
| API | OpenAI-compatible `/v1/chat/completions` | pending |

## 6. Open questions

- **Port / DNS**: expose as `http://<worker>:8080`? Or TLS via existing
  `*.ffilt.us` proxy (self-signed like `llm.ffilt.us`)? Decision affects
  `VISION_BASE` and whether the agent needs `verify=False`.
- **Quantization**: F16 (better accuracy, ~3.7GB working set) vs Q4_K_M
  (fits 4GB VRAM cleanly). Default: Q4_K_M on this GPU.
- **Auth**: open on LAN, or token-gated? Default: open on trusted LAN.
