FROM python:3.10-slim

LABEL maintainer="PAOP Team <team@example.com>"
LABEL description="Pedantic Agent Orchestration Platform"
LABEL version="1.0.0"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set working directory
WORKDIR /app

# Create non-root user
RUN adduser --disabled-password --gecos "" paop
RUN chown -R paop:paop /app

# Install Python dependencies
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-external.txt
RUN pip install --no-cache-dir python-dotenv aiohttp

# Install sitecustomize.py to fix import issues
COPY sitecustomize.py /usr/local/lib/python3.10/site-packages/


# Copy source code
COPY src ./src
COPY config ./config
COPY scripts ./scripts

# Make scripts executable
RUN chmod +x ./scripts/*.sh

# Set proper permissions
RUN chown -R paop:paop /app

# Switch to non-root user
USER paop

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Use our docker_entrypoint.sh as the entrypoint
ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]

# Command to run
CMD ["python", "/app/src/external_interface/main.py"]
