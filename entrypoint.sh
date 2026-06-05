#!/bin/bash
set -e

echo "=== Harness Eval: Configuring ccr ==="

api_timeout_ms="${API_TIMEOUT_MS:-7200000}"

mkdir -p "$HOME/.claude-code-router"
cat > "$HOME/.claude-code-router/config.json" <<EOF
{
  "LOG": false,
  "LOG_LEVEL": "info",
  "CLAUDE_PATH": "",
  "HOST": "127.0.0.1",
  "PORT": 3456,
  "APIKEY": "",
  "API_TIMEOUT_MS": "${api_timeout_ms}",
  "PROXY_URL": "",
  "NON_INTERACTIVE_MODE": true,
  "transformers": [],
  "Providers": [
    {
      "name": "custom",
      "api_base_url": "http://127.0.0.1:3458/v1/chat/completions",
      "api_key": "proxy-placeholder",
      "models": ["${MODEL_NAME}"],
      "transformer": {
        "use": ["OpenAI"]
      }
    }
  ],
  "Router": {
    "default": "custom,${MODEL_NAME}",
    "background": "custom,${MODEL_NAME}",
    "think": "custom,${MODEL_NAME}",
    "longContext": "custom,${MODEL_NAME}",
    "longContextThreshold": 60000,
    "webSearch": "custom,${MODEL_NAME}",
    "image": "custom,${MODEL_NAME}"
  },
  "CUSTOM_ROUTER_PATH": ""
}
EOF

echo "ccr config written."

if [ ! -f /workspace/CLAUDE.md ]; then
    echo "Error: /workspace/CLAUDE.md not found"
    exit 1
fi

cd /workspace

rm -rf .git
if git init -q && git add -A && git commit -q -m "initial" --allow-empty; then
    echo "git workspace initialized."
else
    echo "warning: git workspace initialization failed; continuing without an initial commit." >&2
    rm -rf .git
fi

if [ "${CLAUDE_NATIVE_ANTHROPIC:-}" = "1" ]; then
    echo "=== Using native Anthropic endpoint for Claude Code ==="
    export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-${BASE_URL}}"
    export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-${API_KEY}}"
    export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-${ANTHROPIC_AUTH_TOKEN}}"
    export CLAUDE_MODEL_NAME="${ANTHROPIC_MODEL:-${MODEL_NAME}}"
else
    echo "=== Starting ccr service ==="
    ccr start &
    sleep 2

    echo "=== Starting model proxy ==="
    WORKSPACE=/workspace UPSTREAM_BASE_URL="${BASE_URL}" UPSTREAM_API_KEY="${API_KEY}" node /model-proxy.js &
    sleep 1

    export ANTHROPIC_BASE_URL="http://127.0.0.1:3457"
    export ANTHROPIC_AUTH_TOKEN="placeholder"
    export ANTHROPIC_API_KEY="placeholder"
    export OPENAI_BASE_URL="http://127.0.0.1:3457/v1"
    export OPENAI_API_KEY="sk-placeholder"
    export CLAUDE_MODEL_NAME="${CLAUDE_MODEL_NAME:-claude-sonnet-4-6}"
fi

export MODEL_NAME="${MODEL_NAME}"
export CLAUDE_REASONING_EFFORT="${CLAUDE_REASONING_EFFORT:-}"
export NO_PROXY="127.0.0.1"
export DISABLE_TELEMETRY="true"
export DISABLE_COST_WARNINGS="true"
export API_TIMEOUT_MS="${api_timeout_ms}"

echo "=== Starting Claude Code ==="

claude_args=(
    -p "Read and follow all instructions in CLAUDE.md. Complete the task and write all output files in the current directory."
    --dangerously-skip-permissions
    --output-format text
    --model "${CLAUDE_MODEL_NAME}"
)

if [ -n "$CLAUDE_REASONING_EFFORT" ]; then
    claude_args+=(--effort "$CLAUDE_REASONING_EFFORT")
fi

set +e
claude "${claude_args[@]}" > /workspace/claude_output.log 2>&1
claude_status=$?
set -e

if [ "$claude_status" -eq 0 ]; then
    echo "=== Task completed ==="
else
    echo "=== Task failed: Claude Code exited with status $claude_status ==="
fi

exit "$claude_status"
