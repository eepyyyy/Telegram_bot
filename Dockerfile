# Use official Astral UV image with Python 3.14
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

# Install system runtime dependencies: FFmpeg, curl, ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install project dependencies first (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy project files
COPY . .

# Ensure static directories and mounts exist
RUN mkdir -p downloads backups

# Default environment variables
ENV PYTHONUNBUFFERED=1
ENV DOWNLOAD_MODE=ytdlp

# Command to run the bot
CMD ["uv", "run", "python", "index.py"]
