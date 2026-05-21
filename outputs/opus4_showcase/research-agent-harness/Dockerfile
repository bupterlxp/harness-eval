FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy harness code
COPY harness/ ./harness/

# Create output directory
RUN mkdir -p /app/output

# Environment variables (override at runtime)
ENV OPENAI_BASE_URL=https://api.openai.com/v1
ENV OPENAI_API_KEY=""
ENV MODEL_NAME=gpt-4o-mini

# Default entrypoint
ENTRYPOINT ["python", "-m", "harness"]
CMD ["-p", "What is the current state of quantum computing?", "--output-dir", "/app/output/"]
