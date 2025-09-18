FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORKSPACE_DIR=/workspace \
    GENERATED_DIR=/workspace/generated_api \
    HOST=0.0.0.0

WORKDIR /workspace

# System tools
# Avoid installing large unnecessary packages to reduce layer size and disk usage
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini supervisor ca-certificates curl git && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Optional: install Node.js/npm and nano (enabled via build-arg)
ARG INSTALL_NODE_NANO=false
RUN if [ "$INSTALL_NODE_NANO" = "true" ]; then \
      set -eux; \
      apt-get update; \
      apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
      curl -fsSL https://deb.nodesource.com/setup_20.x | bash -; \
      apt-get install -y --no-install-recommends nodejs nano; \
      npm i -g @anthropic-ai/claude-code; \
      apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*; \
    fi

# Python deps
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Project files
COPY mcp_server ./mcp_server
COPY claude_code ./claude_code
COPY generated_api ./generated_api
COPY supervisord.conf /etc/supervisord.conf

EXPOSE 8000 8300 9000

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["supervisord","-c","/etc/supervisord.conf"]
