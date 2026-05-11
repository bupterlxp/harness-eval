#!/bin/bash
set -e

# Generate claude-code-router config from env vars
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

# Read the CLAUDE.md prompt
if [ ! -f /workspace/CLAUDE.md ]; then
    echo "Error: /workspace/CLAUDE.md not found"
    exit 1
fi

PROMPT=$(cat /workspace/CLAUDE.md)

cd /workspace

# Use ccr code to launch claude code through the router
ccr code --dangerously-skip-permissions -p "$PROMPT" --output-format text > /workspace/claude_output.log 2>&1

echo "Task completed. Output in /workspace/"
