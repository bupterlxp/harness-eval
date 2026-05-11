#!/bin/bash
set -e

echo "=== Harness Eval: Configuring ccr ==="

mkdir -p "$HOME/.claude-code-router"
cat > "$HOME/.claude-code-router/config.json" <<EOF
{
  "LOG": false,
  "LOG_LEVEL": "info",
  "CLAUDE_PATH": "",
  "HOST": "127.0.0.1",
  "PORT": 3456,
  "APIKEY": "",
  "API_TIMEOUT_MS": "600000",
  "PROXY_URL": "",
  "NON_INTERACTIVE_MODE": true,
  "transformers": [],
  "Providers": [
    {
      "name": "custom",
      "api_base_url": "${BASE_URL}",
      "api_key": "${API_KEY}",
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

git init -q
git add -A
git commit -q -m "initial" --allow-empty

echo "=== Starting ccr service ==="
ccr start &
sleep 2

echo "=== Starting model proxy ==="
node /model-proxy.js &
sleep 1

export ANTHROPIC_BASE_URL="http://127.0.0.1:3457"
export ANTHROPIC_AUTH_TOKEN="placeholder"
export NO_PROXY="127.0.0.1"
export DISABLE_TELEMETRY="true"
export DISABLE_COST_WARNINGS="true"
export API_TIMEOUT_MS="600000"

echo "=== Starting Claude Code ==="

claude -p "Read and follow all instructions in CLAUDE.md. Complete the task and write all output files in the current directory." \
    --dangerously-skip-permissions \
    --output-format text \
    --model "claude-sonnet-4-6" \
    > /workspace/claude_output.log 2>&1 || true

echo "=== Task completed ==="
