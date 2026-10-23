# FLOW STATE

FLOW STATE is a Streamlit simulator for UAV bandwidth-management policies. All
network conditions, traffic allocations, and performance figures are simulated;
they are not field measurements and the application does not control real UAVs.

## Architecture

- `decisions.py` is the deterministic baseline and the authority for the four
  policy action mappings.
- `ai_agent.py` calls a separately running Strands Decider service using its
  constrained typed-choice API. It validates inputs and output, maps only the
  four allowed policy IDs to actions from `decisions.py`, applies the emergency
  safety override, and can fall back to the deterministic baseline.
- `scheduler.py` owns traffic allocation. `metrics.py` owns simulated delivery
  metrics and policy comparisons.
- `simulator.py` generates repeatable seeded network scenarios.
- `app.py` offers deterministic and AI selection modes and compares their
  decisions with identical scenario inputs.

## Deterministic baseline

The rule-based policy engine remains usable without an inference service. Its
four evaluation scenarios currently produce these outputs:

| Scenario | Inputs (bandwidth, latency, loss, emergency) | Baseline output |
|---|---|---|
| Normal | 5 Mbps, 70 ms, 1%, false | `BALANCED` |
| Moderate | 2 Mbps, 180 ms, 5%, false | `PROTECT_TELEMETRY` |
| Severe | 0.5 Mbps, 350 ms, 15%, false | `DEFER_SENSORS` |
| Emergency | 1.5 Mbps, 220 ms, 6%, true | `REDUCE_VIDEO` |

These are expected evaluation targets, not promises about model output.

## Strands Decider checkpoint

The target checkpoint is
[`StrandsAgents/strands-decider-2B-qwen3.5-v1-2610`](https://huggingface.co/StrandsAgents/strands-decider-2B-qwen3.5-v1-2610).
The official [inference guide](https://github.com/strands-labs/strands-decider/blob/main/docs/inference.md)
documents typed `choice` decisions and the HTTP `POST /v1/systemone` endpoint.
The adapter submits `state` plus a `questions.policy` choice question and reads
`answers.policy.choice`, `answers.policy.confidence`, and the per-policy
probabilities from the response. The installed Strands schema requires numeric
confidence and probabilities; missing or malformed values cause deterministic
fallback. The server's `/health` endpoint is the readiness check. The adapter
never executes model text and model output cannot redefine scheduler actions.

Verified upstream details (checked 2026-10-21):

- The source repository is [strands-labs/strands-decider](https://github.com/strands-labs/strands-decider),
  and the checkpoint's main home is the Hugging Face `StrandsAgents` organization.
- The official inference guide demonstrates Python 3.12 and specifies Python
  device paths for CUDA, MPS, and CPU. The upstream `pyproject.toml` currently
  declares Python `>=3.10`. The checkpoint also has a CLI `ask` and `serve`
  interface.
- Current upstream runtime dependencies include `torch>=2.7`,
  `transformers>=5.15,<6`, `peft>=0.21`, `accelerate>=0.34`,
  `huggingface_hub>=1.5`, and serving dependencies such as FastAPI and Uvicorn.
  CPU/MPS extras add no packages beyond the base install; CUDA additionally
  uses `flash-linear-attention`, and its optional `causal-conv1d` kernel needs
  a local CUDA toolkit to compile.
- The request shape is `{"state": ..., "questions": {"id": {"type": "choice",
  "instructions": ..., "criteria": {"label": "description"}}}}`.
  The response contains `model`, `answers`, and `usage`; a choice answer contains
  `type`, `choice`, `confidence`, and `probabilities`.
- The server command is `strands-decider serve <checkpoint> --port 8000`; it
  binds to `127.0.0.1` by default. `GET /health` reports `status: "ok"`, model,
  checkpoint, base model, device, and model configuration. Invalid request
  schemas return HTTP 422; server inference failures return an HTTP error.
- The published checkpoint is an adapter/readout, not a self-contained base
  model. First use downloads approximately 4.5 GB of Qwen base weights.
- The official inference guide estimates about 9 GB GPU memory or 19 GB CPU
  memory for E2B, plus activations. CPU inference is supported but slower.
- Upstream estimates about 9 GB GPU memory or 19 GB CPU memory, plus
  activations. The local Strands environment is CPU-only, and the NVIDIA
  Quadro T1000 has 4 GB VRAM. The user reports the exact checkpoint is already
  running on CPU and a real inference request succeeded in about 2.9 seconds.
  The verification harness sees snapshot directories for the checkpoint and
  base model; directory presence alone does not prove every weight is present.
  Avoid starting a second model instance on this host. FLOW STATE itself needs
  only `requests`, not PyTorch or Transformers.

Primary upstream references:

- [Official inference documentation](https://github.com/strands-labs/strands-decider/blob/main/docs/inference.md)
- [Official repository and CLI/server examples](https://github.com/strands-labs/strands-decider)
- [Published checkpoint](https://huggingface.co/StrandsAgents/strands-decider-2B-qwen3.5-v1-2610)

### Run the separate local inference service

The FLOW STATE adapter talks only to the local Strands HTTP service. Your
current setup reports that the target checkpoint is already serving on CPU and
that a real request succeeded. If that server is already running, leave it up
and start only FLOW STATE as shown below. To start the service manually when
its weights and dependencies are already available, use Terminal 1:

```bash
cd ~/strands-decider
source .venv/bin/activate
strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --host 127.0.0.1 --device cpu --port 8000 --max-batch 1
```

Stop the server with Ctrl+C. On supported hardware, CUDA serving uses the
upstream `cuda` extra; the guide notes `causal-conv1d` may require compilation
with a local CUDA toolkit. This project does not install or compile it. The
upstream guide estimates about 19 GB RAM for CPU FP32 weights plus activations;
do not attempt a cold model load if the weights are absent or available memory
is insufficient. This integration does not download weights or start the
service automatically.

The upstream one-shot CLI is `strands-decider ask CHECKPOINT --state TEXT
--choice 'QUESTION=OPTION_A,OPTION_B' --device cpu`; add `--json` for its typed
response. `serve` is the interface used by the app adapter.

In another terminal, check readiness and send one real inference request:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/v1/systemone \
  -H 'content-type: application/json' \
  -d '{"state":{"bandwidth_mbps":5,"latency_ms":70,"packet_loss_pct":1,"emergency":false},"questions":{"policy":{"type":"choice","instructions":"Choose the bandwidth policy for these network conditions.","criteria":{"BALANCED":"Normal allocation","PROTECT_TELEMETRY":"Reduce video and prioritize telemetry","REDUCE_VIDEO":"Minimize video and prioritize telemetry","DEFER_SENSORS":"Defer sensors and prioritize telemetry"}}}}'
```

Stop the server with Ctrl+C in its terminal. The server has no authentication by
default; keep it on localhost for local experiments, or secure any remote
deployment according to the upstream security guidance.

## Run FLOW STATE

The dashboard uses the **Quiet Flight** interface: warm cream surfaces, sage and
coral accents, Fraunces and Source Sans 3 typography, responsive simulator
controls, and an editorial layout. Google Fonts are requested by the browser;
the page includes local serif and sans-serif fallbacks. Decision logic,
traffic allocation, metrics, and comparison values continue to come from the
Python modules documented above.

The app uses Streamlit and Requests for the dashboard and Strands adapter, and
Boto3 for the optional, user-triggered Bedrock explanation. The Strands model
runtime stays in its separate environment. To install dependencies in a fresh
checkout, run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

To start the dashboard from the FLOW STATE repository:

In Terminal 2, start the dashboard with the existing FLOW STATE environment:

```bash
cd ~/Desktop/flow-state
source .venv/bin/activate
export FLOW_STATE_AI_URL=http://127.0.0.1:8000
export FLOW_STATE_AI_TIMEOUT_SECONDS=30
python -m streamlit run app.py
```

`app.py` is the Streamlit entry point; `styles.css` is loaded and injected by
the app and is not a page to run directly.

Select **Deterministic baseline** to work without a model service. Select
**Strands Decider AI** to call the configured service. The UI reports whether a
decision came from Strands inference or baseline fallback and shows the same
conditions' baseline policy. It also compares simulated metrics for both
decisions using the same scheduler and metrics code. Choosing AI mode does not
guarantee real inference; inspect the displayed source and fallback status.
Submit **Apply inputs / request new AI decision** to apply the current values.
In AI mode, each deliberate submit requests a fresh decision; unrelated
dashboard reruns reuse the last decision. A changed input or service
configuration shows the baseline until you submit, so edits never trigger an
unprompted model call.
Mock responses identify themselves with model name `mock`,
`mock-strands-decider`, or `test-mock` and are labeled as mock. Unit tests use
mocked HTTP responses and never contact a service.

The separate **Generate Nova Lite explanation** button makes one optional
Bedrock request for the currently selected policy. Its SDK client uses a
3-second connection timeout, a 20-second read timeout, and one total attempt.
If Bedrock is unavailable or returns invalid content, the UI labels its local
fallback as local text; it never presents that text as Bedrock output.

### Adapter configuration

| Environment variable | Default | Meaning |
|---|---|---|
| `FLOW_STATE_AI_URL` | `http://127.0.0.1:8000` | Base URL of the Strands Decider server |
| `FLOW_STATE_AI_TIMEOUT_SECONDS` | `30` | Read timeout; connect timeout is capped at 5 seconds |
| `FLOW_STATE_AI_FALLBACK` | `1` | Use `decisions.choose_policy()` after request or response failure |

Set `FLOW_STATE_AI_FALLBACK=0` to make the adapter raise
`DecisionInferenceError` on inference failure, useful for strict evaluation.
Invalid inputs always raise and are never replaced with defaults. The adapter
handles connection errors, timeouts, HTTP errors, malformed JSON, missing
fields, missing confidence or probabilities, and unsupported policy IDs. Missing
confidence is never fabricated; the response falls back instead. Emergency
inputs always resolve to `REDUCE_VIDEO`, whose authoritative action mapping
gives telemetry `high_priority`, regardless of model recommendation or
confidence.

## Tests and evaluation

Run all offline unit, UI, and mocked-service tests (no real service, GPU, cloud
credentials, or checkpoint download needed):

```bash
.venv/bin/python -m unittest discover -v
```

This command uses only offline tests and mocked model/service responses. The
real Strands integration test is skipped unless explicitly enabled. No AWS
credentials or Bedrock calls are needed for the test suite. For a reproducible
report of all four deterministic baseline scenarios and their **simulated**
metrics, run:

```bash
.venv/bin/python scripts/evaluate_offline.py
```

The report is written to `reports/offline-evaluation.json` (ignored by Git),
contains no timestamp, and records zero model calls. Choose a different path
with `--output PATH.json`.

The real-service check is separate and skipped by default. Start the service as
above, then run:

```bash
FLOW_STATE_RUN_INTEGRATION=1 FLOW_STATE_AI_FALLBACK=0 .venv/bin/python -m unittest test_strands_integration -v
```

The offline test matrix includes normal, moderate, severe, and emergency
conditions. It checks deterministic baseline expectations separately from
mocked model recommendations. One fixture deliberately disagrees in the severe
case. These mocks make evaluation repeatable; they do not predict or constrain
what the live model will recommend. Review a live/model decision beside the
baseline shown for the exact same inputs. A disagreement is reported, not
automatically treated as a model failure.

The dashboard presents the model's reported confidence as a percentage and a
bar, without applying an automatic confidence cutoff. Confidence is the
model-reported value, not a calibrated guarantee of correctness or a simulated
performance score. The model recommendation is shown separately from the final
policy. In emergency mode, the deterministic override selects `REDUCE_VIDEO`
even if the model recommends something else. The AI-versus-baseline table
shows simulated scheduler/metrics results for the final policy after fallback
or override; these are not real-world UAV measurements.

### Live evaluation report

With the local Strands service running, generate one JSON report using four
fixed scenarios (one request each):

```bash
.venv/bin/python scripts/evaluate_live.py
```

The report is written under ignored `reports/` by default. Use `--output
PATH.json` to choose another path. The runner uses `FLOW_STATE_AI_URL` and
`FLOW_STATE_AI_TIMEOUT_SECONDS` through the existing adapter. Model choices and
confidence are real service responses; allocation/performance metrics are
simulated. Results vary with the model and runtime environment. Service errors
or fallback make the report incomplete and the command exits nonzero; remaining
scenarios are recorded without making extra requests.

Most recently verified offline test results should be taken from the test run
for the current checkout; historical results are not a substitute for that
run. Streamlit UI coverage uses headless `AppTest`, not a visual browser.

The offline UI smoke test renders the baseline dashboard and checks the visible
source labels. Adapter behavior is covered by mocked tests. The opt-in test
against a live Strands service is not part of the offline verification, and no
current service or checkpoint status is implied here.

### Safe local verification harness

Run the repeatable local verification workflow from any working directory:

```bash
bash ~/Desktop/flow-state/scripts/verify_local.sh
```

It uses the FLOW STATE `.venv` interpreter explicitly and checks repository and
import sanity, the complete `unittest` suite, scoped Python compilation, Git
whitespace errors, and a bounded Streamlit HTTP response on `127.0.0.1`. It
also checks the separate Strands checkout's route and schema declarations with
AST source inspection and reports cache, memory, disk, and CUDA information
when available. Adapter behavior is exercised by the mocked unit tests. The
script does not install dependencies, make external network requests, download
weights, load the checkpoint, start Strands, or change system configuration.
It cleans up its temporary log directory and only the Streamlit process it
started. The HTTP check is not a visual browser test.

Optional settings are bounded and validated before use:

```bash
FLOW_STATE_VERIFY_PORT=8765 FLOW_STATE_VERIFY_TIMEOUT=30 bash scripts/verify_local.sh
```

The port must be 1024–65535; the startup deadline must be 1–120 seconds. The
defaults are port `8765` and timeout `30` seconds. `--help` prints usage.

The summary marks each stage `PASS`, `FAIL`, `BLOCKED`, or `INFO`: PASS means
the check actually completed; FAIL means an executed required check failed;
BLOCKED means the environment prevented a required check or its prerequisite
was absent; INFO is diagnostic-only and does not determine overall success.
The harness always reports `Live Strands HTTP service test: NOT RUN` and
`Real checkpoint inference: NOT RUN`. Source inspection and mocked adapter
tests validate the contract without claiming live inference.

Troubleshooting: if imports or tests fail due to missing packages, install
dependencies only through the separately managed project setup process; this
harness deliberately does not repair environments. Read the unittest failure
and run that test directly with `.venv/bin/python -m unittest ...`. If the
localhost smoke test is BLOCKED because local sockets are restricted, rerun in
an environment that permits loopback sockets; the harness does not retry via
another interface. A port conflict or app startup error is reported with the
captured Streamlit log excerpt. Missing `~/strands-decider` files block only
source contract verification; cache and hardware reporting remain informational.

For a fair policy comparison, both AI and baseline decisions use the same
bandwidth, latency, packet loss, scheduler, and metric functions. Repeatable
scenario simulation remains seeded. Model agreement with the expected target
scenarios is an evaluation result and is not forced by the adapter.

## Troubleshooting

- **Connection refused or timeout:** verify the separate server is running and
  `curl http://127.0.0.1:8000/health` reports readiness; check `FLOW_STATE_AI_URL`.
- **HTTP 422:** check server/model compatibility and request-schema errors in
  the server log. The adapter uses the documented `/v1/systemone` schema.
- **Fallback displayed:** the UI is still usable; inspect its error text and
  server logs. Set fallback to `0` when a failed inference must fail evaluation.
- **Out of memory:** the target checkpoint is too large for this host's GPU and
  RAM according to upstream estimates. Run it on a larger machine; this app
  does not launch the server or download weights.
- **Unexpected policy difference:** compare the model decision and confidence
  with the baseline shown for the identical input. Metrics remain simplified
  simulation results, not evidence of field performance.
