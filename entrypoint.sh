#!/bin/bash
set -e

# Generate claude-code-router config from env vars
cat > /root/.claude-code-router/config.json <<EOF
{
  "providers": [
    {
      "name": "custom",
      "apiKey": "${API_KEY}",
      "baseURL": "${BASE_URL}"
    }
  ],
  "router": {
    "default": {
      "provider": "custom",
      "model": "${MODEL_NAME}"
    },
    "background": {
      "provider": "custom",
      "model": "${MODEL_NAME}"
    },
    "thinking": {
      "provider": "custom",
      "model": "${MODEL_NAME}"
    }
  }
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
# --dangerously-skip-permissions: no human confirmation needed in container
ccr code --dangerously-skip-permissions -p "$PROMPT" --output-format text > /workspace/claude_output.log 2>&1

echo "Task completed. Output in /workspace/"
