FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tmux \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for Claude CLI
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code

# Copy and install hook forwarder script
COPY runners/cerb-hook-forward.sh /usr/local/bin/cerb-hook
RUN chmod +x /usr/local/bin/cerb-hook

# Set working directory
WORKDIR /workspace

# Container will run tmux in foreground (CMD provided at runtime per session)
