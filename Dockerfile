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

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-cli

# Set working directory
WORKDIR /workspace

# Container will run tmux in foreground (CMD provided at runtime per session)
