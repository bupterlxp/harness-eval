FROM python:3.11-slim

# System dependencies for matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash agent
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy harness code
COPY harness/ /app/harness/

# Create working and output directories
RUN mkdir -p /workspace /output && chown -R agent:agent /workspace /output /app

# Switch to non-root user
USER agent

# LLM configuration via environment variables (do NOT hardcode)
ENV OPENAI_BASE_URL=""
ENV OPENAI_API_KEY=""
ENV MODEL_NAME=""

# Default working directory for data files
WORKDIR /workspace

# Entry point
ENTRYPOINT ["python", "-m", "harness"]
CMD ["--help"]
