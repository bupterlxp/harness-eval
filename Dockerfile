FROM node:20-slim

RUN apt-get update && apt-get install -y \
    curl \
    git \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code and Claude Code Router globally
RUN npm install -g @anthropic-ai/claude-code @musistudio/claude-code-router

# Create workspace (agent works here, no claude code source)
RUN mkdir -p /workspace /root/.claude-code-router

WORKDIR /workspace

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
