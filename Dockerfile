FROM python:3.12-slim

LABEL org.opencontainers.image.title="Continuity Orchestrator"
LABEL org.opencontainers.image.description="Policy-first automation system"
LABEL org.opencontainers.image.source="https://github.com/cyberpunk042/continuity-orchestrator"

# Install system dependencies
#   curl: uv bootstrap + healthcheck
#   git:  git-sync mode
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash continuity

# Set working directory
WORKDIR /app

# Copy dependency files first (better caching)
COPY pyproject.toml .
COPY src ./src

# Install uv — fast package manager for lazy-installs at runtime
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Install core dependencies only (Tier 0, ~14MB)
# Adapter/feature deps are lazy-installed on first use via src/deps.py
RUN /root/.local/bin/uv pip install --system --no-cache-dir -e .

# Make system site-packages writable by continuity user
# so lazy-installs at runtime work without root
RUN chown -R continuity:continuity \
    $(python -c "import site; print(site.getsitepackages()[0])") \
    /app

# Install uv for the non-root user too
USER continuity
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
USER root

# Copy the rest of the application
COPY policy ./policy
COPY templates ./templates
COPY content ./content
COPY scripts ./scripts

# Create data directories
RUN mkdir -p /data/state /data/audit && \
    chown -R continuity:continuity /app /data

# uv cache volume — lazy-installed packages persist across container restarts
VOLUME /home/continuity/.cache/uv

# Switch to non-root user
USER continuity

# Ensure uv is on PATH for the non-root user
ENV PATH="/home/continuity/.local/bin:${PATH}"

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
