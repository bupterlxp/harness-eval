FROM node:20-slim

RUN apt-get update && apt-get install -y \
    curl \
    git \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code @musistudio/claude-code-router

RUN mkdir -p /workspace /root/.claude-code-router

RUN git config --global user.email "harness@eval.local" && \
    git config --global user.name "Harness Eval"

WORKDIR /workspace

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
