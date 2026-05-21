FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    grep \
    findutils \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash agent

# Set up workspace
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy harness code
COPY harness/ /app/harness/

# Create workspace directory for tasks
RUN mkdir -p /workspace && chown agent:agent /workspace

# Switch to non-root user
USER agent

# Set environment variables (overridable at runtime)
ENV OPENAI_BASE_URL="https://api.openai.com/v1"
ENV OPENAI_API_KEY=""
ENV MODEL_NAME="gpt-4o"

# Default workspace
WORKDIR /workspace

ENTRYPOINT ["python", "-m", "harness"]
