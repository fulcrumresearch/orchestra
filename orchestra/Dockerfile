FROM python:3.12-slim

# Accept build arguments for user ID and group ID
ARG USER_ID=1000
ARG GROUP_ID=1000

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tmux \
    git \
    curl \
    ca-certificates \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for Claude CLI
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code

# Copy and install hook forwarder script
COPY runners/orchestra-hook-forward.sh /usr/local/bin/orchestra-hook
RUN chmod +x /usr/local/bin/orchestra-hook

# Create user with matching UID/GID
RUN groupadd -g ${GROUP_ID} executor || true && \
    useradd -u ${USER_ID} -g ${GROUP_ID} -m -s /bin/bash executor && \
    install -d -o executor -g ${GROUP_ID} /workspace && \
    printf 'executor ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/executor && \
    chmod 0440 /etc/sudoers.d/executor

# Set working directory
WORKDIR /workspace

# Switch to non-root user
USER executor

# Container will run tmux in foreground (CMD provided at runtime per session)
