# Resume Matcher Docker Image
# Multi-stage build for optimized image size

# ============================================
# Stage 1: Build Frontend
# ============================================
FROM node:22-bookworm AS frontend-builder

# Build argument for API URL (allows customization at build time)
# Default routes requests through Next.js rewrites on the same origin.
ARG NEXT_PUBLIC_API_URL=/
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

WORKDIR /app/frontend

# Copy package files first for better caching
COPY apps/frontend/package*.json ./

# Install dependencies
RUN npm ci

# Copy frontend source
COPY apps/frontend/ ./

# Build the frontend
RUN npm run build

# ============================================
# Stage 2: Final Image
# ============================================
FROM python:3.13-slim-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    # Playwright dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    # CJK fonts for Chinese/Japanese/Korean PDF rendering via Playwright
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# LaTeX Engine (optional)
# ============================================
# Tectonic, not TeX Live: one ~30MB static binary that fetches the packages a
# document actually needs, versus a multi-GB distribution. Build with
# `--build-arg INSTALL_LATEX=false` to drop LaTeX export entirely - the app
# detects the missing engine and offers a .tex download instead.
ARG INSTALL_LATEX=true
ARG TECTONIC_VERSION=0.17.0
RUN if [ "$INSTALL_LATEX" = "true" ]; then \
      set -eux; \
      case "$(dpkg --print-architecture)" in \
        amd64) TECTONIC_ARCH=x86_64 ;; \
        arm64) TECTONIC_ARCH=aarch64 ;; \
        *) echo "No tectonic build for $(dpkg --print-architecture)" >&2; exit 0 ;; \
      esac; \
      curl -fsSL -o /tmp/tectonic.tar.gz \
        "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-${TECTONIC_ARCH}-unknown-linux-musl.tar.gz"; \
      tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin tectonic; \
      rm /tmp/tectonic.tar.gz; \
      tectonic --version; \
    fi

WORKDIR /app

# Copy Node.js runtime from frontend builder for reproducible runtime behavior.
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node

# ============================================
# Backend Setup
# ============================================
COPY apps/backend/pyproject.toml /app/backend/
COPY apps/backend/alembic.ini /app/backend/
COPY apps/backend/migrations /app/backend/migrations
COPY apps/backend/app /app/backend/app

WORKDIR /app/backend

# Install Python dependencies
RUN pip install .

# ============================================
# Frontend Setup
# ============================================
WORKDIR /app/frontend

# Copy standalone frontend runtime from builder stage
COPY --from=frontend-builder /app/frontend/.next/standalone ./
COPY --from=frontend-builder /app/frontend/.next/static ./.next/static
COPY --from=frontend-builder /app/frontend/public ./public

# ============================================
# Startup Script
# ============================================
COPY docker/start.sh /app/start.sh
# Convert CRLF to LF (fixes Windows line ending issues) and make executable
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

# ============================================
# Data Directory & Volume
# ============================================
RUN mkdir -p /app/backend/data

# Create a non-root user for security
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

# Install Playwright Chromium as appuser (so browsers are in correct location)
RUN python -m playwright install chromium

# Warm Tectonic's TeX bundle into the image as appuser. Without this the
# first user export pays a ~300MB download, and an offline deployment never
# compiles at all.
RUN if command -v tectonic >/dev/null 2>&1; then \
      set -eux; \
      mkdir -p /tmp/texwarm && cd /tmp/texwarm; \
      printf '%s' '\documentclass[a4paper,10pt]{article}\usepackage{url}\usepackage{parskip}\RequirePackage{color}\RequirePackage{graphicx}\usepackage[usenames,dvipsnames]{xcolor}\usepackage[scale=0.9]{geometry}\usepackage{tabularx}\usepackage{enumitem}\usepackage{supertabular}\usepackage{titlesec}\usepackage{multicol}\usepackage{multirow}\usepackage{fontawesome5}\usepackage[unicode,draft=false]{hyperref}\begin{document}warm\end{document}' > warm.tex; \
      tectonic --keep-logs --outdir . warm.tex; \
      cd / && rm -rf /tmp/texwarm; \
    fi

# Expose the public port (backend remains internal on 8000)
EXPOSE 3000

# Volume for persistent data
VOLUME ["/app/backend/data"]

# Set working directory
WORKDIR /app

# Health check on internal backend port only (independent of host port mapping).
HEALTHCHECK --interval=10s --timeout=10s --start-period=30s --retries=5 \
    CMD curl -f http://127.0.0.1:8000/api/v1/health || exit 1

# Start the application
CMD ["/app/start.sh"]
