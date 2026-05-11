#!/bin/bash
set -e

echo "=== Harness Eval: Configuring ccr ==="

mkdir -p /root/.claude-code-router
cat > /root/.claude-code-router/config.json <<EOF
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

echo "=== Starting Claude Code via ccr ==="

ccr code -p "Read and follow all instructions in CLAUDE.md. Complete the task and write all output files in the current directory." \
    --dangerously-skip-permissions \
    --output-format text \
    > /workspace/claude_output.log 2>&1 || true

echo "=== Task completed ==="
