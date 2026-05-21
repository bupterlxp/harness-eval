FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy harness code
COPY harness/ harness/

# Create output directory
RUN mkdir -p /app/output

# Environment variables (override at runtime)
ENV OPENAI_BASE_URL=https://api.openai.com/v1
ENV OPENAI_API_KEY=""
ENV MODEL_NAME=gpt-4o

# Non-root user for security
RUN useradd -m -s /bin/bash agent && chown -R agent:agent /app
USER agent

ENTRYPOINT ["python", "-m", "harness"]
CMD ["-p", "Write a short story", "--output-dir", "/app/output/"]
