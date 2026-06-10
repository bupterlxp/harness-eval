#!/usr/bin/env bash
set -euo pipefail

BENCHMARKS_ROOT="${BENCHMARKS_ROOT:-/data00/harness-evolve-project/harness_house/benchmarks}"
OUT_ROOT="${OUT_ROOT:-/data00/harness-eval/eval_results/swepro_image_prewarm}"
DATASET="${DATASET:-ScaleAI/SWE-bench_Pro}"
SPLIT="${SPLIT:-test}"
PULL_JOBS="${PULL_JOBS:-4}"
BUILD_WORKERS="${BUILD_WORKERS:-4}"
PULL_RETRIES="${PULL_RETRIES:-12}"
PULL_TIMEOUT_SECONDS="${PULL_TIMEOUT_SECONDS:-1200}"
BUILD_RETRIES="${BUILD_RETRIES:-3}"

mkdir -p "$OUT_ROOT"

usage() {
  cat <<'EOF'
Usage:
  prewarm_swepro_images.sh list
  prewarm_swepro_images.sh pull
  prewarm_swepro_images.sh pull-loop
  prewarm_swepro_images.sh build
  prewarm_swepro_images.sh status
  prewarm_swepro_images.sh all

Environment:
  BENCHMARKS_ROOT=/data00/harness-evolve-project/harness_house/benchmarks
  OUT_ROOT=/data00/harness-eval/eval_results/swepro_image_prewarm
  PULL_JOBS=4
  BUILD_WORKERS=4
  PULL_RETRIES=12
  PULL_TIMEOUT_SECONDS=1200
EOF
}

list_file="$OUT_ROOT/base_images.txt"
pull_ok_file="$OUT_ROOT/pulled.ok"
pull_fail_file="$OUT_ROOT/pulled.fail"
pull_log_dir="$OUT_ROOT/pull_logs"
build_log="$OUT_ROOT/build_agent_images.log"
build_pid_file="$OUT_ROOT/build_agent_images.pid"

generate_list() {
  cd "$BENCHMARKS_ROOT"
  mkdir -p "$OUT_ROOT"
  .venv/bin/python - <<'PY' > "$list_file.tmp"
from benchmarks.swebench.build_images import collect_unique_base_images

for image in collect_unique_base_images("ScaleAI/SWE-bench_Pro", "test", 0, None):
    print(image)
PY
  mv "$list_file.tmp" "$list_file"
  sort -u "$list_file" -o "$list_file"
  echo "Wrote $(wc -l < "$list_file" | tr -d ' ') base images to $list_file"
}

pull_one() {
  local image="$1"
  local safe_name log
  safe_name="$(printf '%s' "$image" | tr '/:' '__')"
  log="$pull_log_dir/${safe_name}.log"

  if grep -Fxq "$image" "$pull_ok_file" 2>/dev/null; then
    echo "SKIP already pulled: $image"
    return 0
  fi

  for attempt in $(seq 1 "$PULL_RETRIES"); do
    {
      echo "[$(date -Is)] pull attempt $attempt/$PULL_RETRIES: $image"
      timeout "$PULL_TIMEOUT_SECONDS" docker pull "$image"
    } >> "$log" 2>&1 && {
      (
        flock 9
        grep -Fxq "$image" "$pull_ok_file" 2>/dev/null || echo "$image" >> "$pull_ok_file"
      ) 9>"$OUT_ROOT/pull.lock"
      echo "OK pulled: $image"
      return 0
    }
    sleep $((attempt * 10))
  done

  (
    flock 9
    grep -Fxq "$image" "$pull_fail_file" 2>/dev/null || echo "$image" >> "$pull_fail_file"
  ) 9>"$OUT_ROOT/pull.lock"
  echo "FAIL pull: $image" >&2
  return 1
}

pull_all() {
  if [[ ! -f "$list_file" ]]; then
    generate_list
  fi
  mkdir -p "$pull_log_dir"
  touch "$pull_ok_file" "$pull_fail_file"

  local pending="$OUT_ROOT/pull.pending"
  grep -Fvx -f "$pull_ok_file" "$list_file" > "$pending" || true
  echo "Pull pending: $(wc -l < "$pending" | tr -d ' ') / $(wc -l < "$list_file" | tr -d ' ')"

  export OUT_ROOT PULL_RETRIES PULL_TIMEOUT_SECONDS pull_ok_file pull_fail_file pull_log_dir
  export -f pull_one
  xargs -r -n 1 -P "$PULL_JOBS" bash -c 'pull_one "$@"' _ < "$pending"
}

pull_loop() {
  if [[ ! -f "$list_file" ]]; then
    generate_list
  fi

  local total ok previous_ok round
  total="$(wc -l < "$list_file" | tr -d ' ')"
  previous_ok=-1
  round=0

  while true; do
    round=$((round + 1))
    ok="$(wc -l < "$pull_ok_file" 2>/dev/null | tr -d ' ' || echo 0)"
    echo "[$(date -Is)] pull-loop round=$round ok=$ok/$total"
    if [[ "$ok" == "$total" ]]; then
      echo "All base images pulled."
      return 0
    fi

    pull_all || true

    ok="$(wc -l < "$pull_ok_file" 2>/dev/null | tr -d ' ' || echo 0)"
    echo "[$(date -Is)] pull-loop completed round=$round ok=$ok/$total"
    if [[ "$ok" == "$total" ]]; then
      echo "All base images pulled."
      return 0
    fi

    if [[ "$ok" == "$previous_ok" ]]; then
      echo "No new images pulled in this round; sleeping before retry."
      sleep 300
    else
      sleep 30
    fi
    previous_ok="$ok"
  done
}

build_agent_images() {
  cd "$BENCHMARKS_ROOT"
  export OPENHANDS_SUPPRESS_BANNER=1
  export DOCKER_BUILDKIT=1
  docker buildx use default >/dev/null 2>&1 || true
  .venv/bin/python -m benchmarks.swebench.build_images \
    --dataset "$DATASET" \
    --split "$SPLIT" \
    --image ghcr.io/openhands/eval-agent-server \
    --target source-minimal \
    --max-workers "$BUILD_WORKERS" \
    --max-retries "$BUILD_RETRIES" \
    --force-build
}

build_background() {
  if [[ -f "$build_pid_file" ]]; then
    local old_pid
    old_pid="$(cat "$build_pid_file" || true)"
    if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
      echo "Build already running: pid=$old_pid log=$build_log"
      return 0
    fi
  fi
  nohup "$0" build-foreground > "$build_log" 2>&1 &
  echo "$!" > "$build_pid_file"
  echo "Started agent image build: pid=$(cat "$build_pid_file") log=$build_log"
}

status() {
  echo "OUT_ROOT=$OUT_ROOT"
  [[ -f "$list_file" ]] && echo "base_images=$(wc -l < "$list_file" | tr -d ' ')" || echo "base_images=missing"
  [[ -f "$pull_ok_file" ]] && echo "pulled_ok=$(wc -l < "$pull_ok_file" | tr -d ' ')" || echo "pulled_ok=0"
  [[ -f "$pull_fail_file" ]] && echo "pulled_fail=$(wc -l < "$pull_fail_file" | tr -d ' ')" || echo "pulled_fail=0"
  echo "docker_sweap_images=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -c 'jefzda/sweap-images' || true)"
  echo "docker_agent_images=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -c 'ghcr.io/openhands/eval-agent-server' || true)"
  echo "docker_builder_images=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -c 'ghcr.io/openhands/eval-builder' || true)"
  echo "docker_buildx_processes=$(pgrep -fc '^docker buildx build' || true)"
  if [[ -f "$build_pid_file" ]]; then
    local pid
    pid="$(cat "$build_pid_file" || true)"
    echo "build_pid=$pid"
    ps -p "$pid" -o pid,stat,etime,cmd || true
  fi
  df -h /data00 || true
}

case "${1:-}" in
  list) generate_list ;;
  pull) pull_all ;;
  pull-loop) pull_loop ;;
  build) build_background ;;
  build-foreground) build_agent_images ;;
  status) status ;;
  all)
    generate_list
    pull_loop
    build_background
    ;;
  ""|-h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
