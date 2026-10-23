#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/verify_local.sh [--help]

Runs offline FLOW STATE checks and a bounded HTTP smoke test on loopback.
Optional settings:
  FLOW_STATE_VERIFY_PORT       Local port (1024..65535), default 8765
  FLOW_STATE_VERIFY_TIMEOUT    Startup deadline (1..120 seconds), default 30

This script never installs packages, downloads/loads models, or starts Strands.
EOF
}

if [[ ${1:-} == --help ]]; then usage; exit 0; fi
if [[ $# -ne 0 ]]; then usage >&2; exit 2; fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
EXPECTED_ROOT="${FLOW_STATE_EXPECTED_ROOT:-$ROOT}"
PYTHON="$ROOT/.venv/bin/python"
STREAMLIT="$ROOT/.venv/bin/streamlit"
PORT="${FLOW_STATE_VERIFY_PORT:-8765}"
TIMEOUT="${FLOW_STATE_VERIFY_TIMEOUT:-30}"

valid_integer() { [[ $1 =~ ^[0-9]+$ ]]; }
if ! valid_integer "$PORT" || (( PORT < 1024 || PORT > 65535 )); then
  echo "ERROR: FLOW_STATE_VERIFY_PORT must be an integer from 1024 to 65535." >&2
  exit 2
fi
if ! valid_integer "$TIMEOUT" || (( TIMEOUT < 1 || TIMEOUT > 120 )); then
  echo "ERROR: FLOW_STATE_VERIFY_TIMEOUT must be an integer from 1 to 120." >&2
  exit 2
fi

declare -A STATUS=()
declare -A DETAILS=()
TMP_DIR=""
SERVER_PID=""
remove_temp_dir() {
  if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
    rm -f -- "$TMP_DIR/unittest.log" "$TMP_DIR/streamlit.log"
    rmdir -- "$TMP_DIR" 2>/dev/null || echo "WARNING: Temporary directory was not empty; left in place: $TMP_DIR" >&2
  fi
  TMP_DIR=""
}
cleanup() {
  local code=$?
  trap - EXIT INT TERM HUP
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  remove_temp_dir
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

stage() { printf '\n===== %s — %s =====\n' "$1" "$2"; }
record() { STATUS["$1"]="$2"; DETAILS["$1"]="$3"; printf '%s: %s — %s\n' "$1" "$2" "$3"; }

stage A "Environment and project sanity"
stage_a_ok=1
if [[ "$ROOT" != "$EXPECTED_ROOT" ]]; then
  record A FAIL "Resolved repository $ROOT; expected $EXPECTED_ROOT"
  stage_a_ok=0
elif [[ ! -f "$ROOT/app.py" || ! -f "$ROOT/ai_agent.py" || ! -f "$ROOT/decisions.py" || ! -f "$ROOT/scheduler.py" || ! -f "$ROOT/metrics.py" || ! -f "$ROOT/simulator.py" ]]; then
  record A FAIL "One or more required project files are missing"
  stage_a_ok=0
elif [[ ! -x "$PYTHON" ]]; then
  record A FAIL "Project interpreter missing: $PYTHON"
  stage_a_ok=0
else
  if "$PYTHON" -c 'import sys; print("Python:", sys.version.split()[0]); print("Executable:", sys.executable)' ; then
    if "$PYTHON" -c 'import ai_agent, decisions, metrics, scheduler, simulator, streamlit, requests' ; then
      record A PASS "Expected repository, interpreter, and local imports verified (no app server started)"
    else
      record A FAIL "A required local import failed"
      stage_a_ok=0
    fi
  else
    record A FAIL "Project interpreter did not run"
    stage_a_ok=0
  fi
fi

stage B "Unit and adapter tests"
if [[ -x "$PYTHON" ]]; then
  if [[ -z "$TMP_DIR" ]]; then TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/flow-state-verify.XXXXXX")"; fi
  test_log="$TMP_DIR/unittest.log"
  set +e
  "$PYTHON" -m unittest discover -v >"$test_log" 2>&1
  test_rc=$?
  set -e
  cat "$test_log"
  read -r passed failed skipped <<<"$("$PYTHON" - "$test_log" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
matches = re.findall(r"Ran (\d+) tests? in [^\n]+\n\n(OK(?: \(skipped=\d+\))?|FAILED \([^\n]*\))", text)
if matches:
    total = int(matches[-1][0]); summary = matches[-1][1]
    skip = int(re.search(r"skipped=(\d+)", summary).group(1)) if "skipped=" in summary else 0
    fail = int(re.search(r"failures=(\d+)", summary).group(1)) if "failures=" in summary else 0
    fail += int(re.search(r"errors=(\d+)", summary).group(1)) if "errors=" in summary else 0
    print(total - fail - skip, fail, skip)
else:
    print(0, 0 if "Ran " not in text else 1, 0)
PY
  )"
  rm -f -- "$test_log"
  if (( test_rc == 0 )); then record B PASS "$passed passed, $failed failed, $skipped skipped (exit $test_rc)"
  else record B FAIL "$passed passed, $failed failed, $skipped skipped (exit $test_rc)"; fi
else
  record B BLOCKED "Project interpreter is unavailable"
fi

stage C "Static checks"
if [[ -x "$PYTHON" ]]; then
  mapfile -t source_files < <(find "$ROOT" -maxdepth 1 -type f -name '*.py' -print | sort)
  set +e
  "$PYTHON" -m compileall -q "${source_files[@]}"
  compile_rc=$?
  set -e
  printf 'compileall exit status: %s\n' "$compile_rc"
else compile_rc=127; fi
set +e
git -C "$ROOT" diff --check
diff_rc=$?
set -e
printf 'git diff --check exit status: %s\n' "$diff_rc"
if (( compile_rc == 0 && diff_rc == 0 )); then record C PASS "Scoped Python compile and diff whitespace checks passed"
else record C FAIL "compileall=$compile_rc, git diff --check=$diff_rc"; fi

stage D "Loopback Streamlit HTTP smoke test"
if [[ ! -x "$STREAMLIT" || ! -f "$ROOT/app.py" ]]; then
  record D BLOCKED "Streamlit executable or app.py is unavailable"
else
  if [[ -z "$TMP_DIR" ]]; then TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/flow-state-verify.XXXXXX")"; fi
  set +e
  launch_check="$($PYTHON - "$PORT" <<'PY' 2>&1
import socket, sys
sock = None
try:
    sock = socket.socket()
    sock.bind(("127.0.0.1", int(sys.argv[1])))
except OSError as exc:
    print(f"{type(exc).__name__}: {exc}")
    sys.exit(3)
finally:
    if sock is not None: sock.close()
PY
  )"
  launch_rc=$?
  set -e
  if (( launch_rc != 0 )); then
    if [[ "$launch_check" == *PermissionError* ]]; then record D BLOCKED "Local sockets are restricted by this environment: $launch_check"
    else record D FAIL "Port $PORT is unavailable: $launch_check"; fi
  else
    set +e
    "$STREAMLIT" run "$ROOT/app.py" --server.headless true --server.address 127.0.0.1 --server.port "$PORT" --browser.gatherUsageStats false >"$TMP_DIR/streamlit.log" 2>&1 &
    SERVER_PID=$!
    set -e
    http_status=""
    smoke_state="FAIL"
    for (( attempt=0; attempt<TIMEOUT*4; attempt++ )); do
      if ! kill -0 "$SERVER_PID" 2>/dev/null; then break; fi
      set +e
      http_status="$("$PYTHON" - "$PORT" <<'PY' 2>/dev/null
import http.client, sys
try:
    conn = http.client.HTTPConnection("127.0.0.1", int(sys.argv[1]), timeout=1)
    conn.request("GET", "/")
    response = conn.getresponse()
    body = response.read(4096).decode("utf-8", "replace")
    print(response.status)
    if response.status != 200 or ("streamlit" not in body.lower() and "<html" not in body.lower()):
        sys.exit(1)
except (OSError, http.client.HTTPException):
    sys.exit(2)
PY
      )"
      poll_rc=$?
      set -e
      if (( poll_rc == 0 )); then smoke_state="PASS"; break; fi
      if (( poll_rc == 1 )); then smoke_state="FAIL"; break; fi
      sleep 0.25
    done
    if [[ "$smoke_state" == PASS ]]; then
      record D PASS "HTTP $http_status from Streamlit on 127.0.0.1:$PORT; localhost smoke test only"
    else
      tail -n 35 "$TMP_DIR/streamlit.log" || true
      record D "$smoke_state" "No successful HTTP 200 within ${TIMEOUT}s (process exit/status: ${http_status:-unavailable})"
    fi
    if kill -0 "$SERVER_PID" 2>/dev/null; then kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; fi
    SERVER_PID=""
    remove_temp_dir
  fi
fi

stage E "Strands adapter contract — source and mocked tests only"
STRANDS_ROOT="$HOME/strands-decider"
STRANDS_PYTHON="$STRANDS_ROOT/.venv/bin/python"
if [[ ! -x "$STRANDS_PYTHON" || ! -f "$STRANDS_ROOT/src/strands_decider/server.py" || ! -f "$STRANDS_ROOT/src/strands_decider/schema.py" ]]; then
  record E BLOCKED "Separate Strands checkout, interpreter, or source schema unavailable"
else
  set +e
  "$STRANDS_PYTHON" - "$STRANDS_ROOT" <<'PY'
import ast, pathlib, sys
root = pathlib.Path(sys.argv[1]) / "src/strands_decider"
server = ast.parse((root / "server.py").read_text())
schema = ast.parse((root / "schema.py").read_text())
routes = set()
for node in ast.walk(server):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app":
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        routes.add((dec.func.attr.upper(), dec.args[0].value))
assert ("POST", "/v1/systemone") in routes, f"Missing inference route: {routes}"
assert ("GET", "/health") in routes, f"Missing health route: {routes}"
classes = {n.name: n for n in schema.body if isinstance(n, ast.ClassDef)}
expected = {
    "SystemOneRequest": {"state", "questions"},
    "ChoiceQuestion": {"type", "instructions", "criteria"},
    "ChoiceAnswer": {"type", "choice", "probabilities", "confidence"},
    "SystemOneResponse": {"model", "answers", "usage"},
}
for cls, fields in expected.items():
    if cls not in classes:
        raise AssertionError(f"Missing schema class {cls}")
    found = set()
    for n in ast.walk(classes[cls]):
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name): found.add(n.target.id)
    if not fields <= found: raise AssertionError(f"{cls}: missing fields {fields-found}")
print("Verified source routes: POST /v1/systemone, GET /health")
print("Verified source request/choice/response schema fields")
PY
  source_rc=$?
  set -e
  if (( source_rc == 0 )); then record E PASS "Installed source contract verified; adapter mocks are covered by Stage B. No Strands server or model imported"
  else record E FAIL "AST source contract check failed (exit $source_rc)"; fi
fi

stage F "Informational model-cache and hardware report"
CHECKPOINT="StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"
BASE_MODEL="Qwen/Qwen3.5-2B-Base"
if [[ -n "${HF_HUB_CACHE:-}" ]]; then CACHE_ROOT="$HF_HUB_CACHE"
elif [[ -n "${HUGGINGFACE_HUB_CACHE:-}" ]]; then CACHE_ROOT="$HUGGINGFACE_HUB_CACHE"
elif [[ -n "${TRANSFORMERS_CACHE:-}" ]]; then CACHE_ROOT="$TRANSFORMERS_CACHE"
elif [[ -n "${HF_HOME:-}" ]]; then CACHE_ROOT="$HF_HOME/hub"
else CACHE_ROOT="$HOME/.cache/huggingface/hub"; fi
for item in "checkpoint|models--StrandsAgents--strands-decider-2B-qwen3.5-v1-2610" "base|models--Qwen--Qwen3.5-2B-Base"; do
  label=${item%%|*}; dir=${item#*|}
  if [[ -d "$CACHE_ROOT/$dir/snapshots" ]] && find "$CACHE_ROOT/$dir/snapshots" -mindepth 1 -maxdepth 1 -type d -print -quit | grep -q .; then
    printf '%s cache: snapshot metadata/directory present at %s\n' "$label" "$CACHE_ROOT/$dir/snapshots"
  else printf '%s cache: not found in recognized cache path %s\n' "$label" "$CACHE_ROOT/$dir"; fi
done
printf 'Target checkpoint: %s\n' "$CHECKPOINT"
if command -v free >/dev/null 2>&1; then free -h || true; else echo 'Memory report: free command unavailable'; fi
if command -v df >/dev/null 2>&1; then df -h "$ROOT" || true; else echo 'Disk report: df command unavailable'; fi
for env_label in project Strands; do
  if [[ "$env_label" == project ]]; then env_python="$PYTHON"; else env_python="$STRANDS_PYTHON"; fi
  if [[ -x "$env_python" ]]; then
    set +e
    cuda_result="$("$env_python" -c 'import torch; print(torch.cuda.is_available())' 2>/dev/null)"
    cuda_rc=$?
    set -e
    if (( cuda_rc == 0 )); then printf '%s environment CUDA available: %s\n' "$env_label" "$cuda_result"
    else printf '%s environment CUDA available: unavailable (Torch missing or import failed)\n' "$env_label"; fi
  else printf '%s environment CUDA available: interpreter unavailable\n' "$env_label"; fi
done
if command -v nvidia-smi >/dev/null 2>&1; then set +e; nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1; gpu_rc=$?; set -e; (( gpu_rc == 0 )) || echo 'GPU report: nvidia-smi could not query a device'; else echo 'GPU report: nvidia-smi unavailable'; fi
printf 'Live Strands HTTP service test: NOT RUN\n'
printf 'Real checkpoint inference: NOT RUN\n'
record F INFO "Diagnostics only; cache presence is not proof of a complete usable checkpoint"

printf '\n===== FINAL SUMMARY =====\n'
for key in A B C D E F; do printf '%s: %s — %s\n' "$key" "${STATUS[$key]:-BLOCKED}" "${DETAILS[$key]:-not completed}"; done
printf 'Application and unit tests: %s\n' "${STATUS[B]:-BLOCKED}"
printf 'Adapter contract tests (mocks/source inspection): %s\n' "${STATUS[E]:-BLOCKED}"
printf 'Local HTTP smoke test: %s\n' "${STATUS[D]:-BLOCKED}"
printf 'Live Strands HTTP service test: NOT RUN\n'
printf 'Real checkpoint inference: NOT RUN\n'
overall=0
for key in A B C D E; do [[ ${STATUS[$key]:-BLOCKED} == PASS ]] || overall=1; done
if (( overall == 0 )); then echo 'Overall required checks: PASS'; else echo 'Overall required checks: FAIL (see stage results)'; fi
exit "$overall"
