FROM node:20-slim

LABEL harness-eval.dev-bmk="1"

RUN apt-get update && apt-get install -y \
    curl \
    docker.io \
    git \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --break-system-packages --no-cache-dir \
    appdirs \
    diskcache \
    py7zr \
    tenacity \
    tqdm \
    numpy \
    pandas \
    pyyaml \
    requests \
    scikit-learn \
    uv

RUN npm install -g @anthropic-ai/claude-code @musistudio/claude-code-router

COPY entrypoint.sh /entrypoint.sh
COPY model-proxy.js /model-proxy.js
RUN chmod +x /entrypoint.sh

RUN useradd -m -s /bin/bash agent && \
    mkdir -p /workspace && \
    chown agent:agent /workspace

USER agent

RUN git config --global user.email "harness@eval.local" && \
    git config --global user.name "Harness Eval"

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
