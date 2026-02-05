FROM python:3.11-slim

LABEL org.opencontainers.image.title="Continuity Orchestrator"
LABEL org.opencontainers.image.description="Policy-first automation system"
LABEL org.opencontainers.image.source="https://github.com/cyberpunk042/continuity-orchestrator"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash continuity

# Set working directory
WORKDIR /app

# Copy dependency files first (better caching)
COPY pyproject.toml .
COPY src ./src

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Install optional adapters
RUN pip install --no-cache-dir \
    twilio \
    httpx \
    praw \
    resend \
    || true

# Copy the rest of the application
COPY policy ./policy
COPY templates ./templates
COPY content ./content

# Create data directories
RUN mkdir -p /data/state /data/audit && \
    chown -R continuity:continuity /app /data

# Switch to non-root user
USER continuity

# Default environment
ENV STATE_FILE=/data/state/current.json
ENV AUDIT_DIR=/data/audit
ENV POLICY_DIR=/app/policy
ENV ADAPTER_MOCK_MODE=false

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -m src.main status || exit 1

# Default command
CMD ["python", "-m", "src.main", "tick"]
