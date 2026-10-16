# ==========================================
# Multi-stage Dockerfile for AWGP Pipeline
# ==========================================

# 1. Build React/Vite Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2. Build Python Backend with ffmpeg
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies (ffmpeg is required for audio slice & mastering)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY src/ ./src/
COPY configs/ ./configs/
COPY api.py run.py ./

# Copy compiled frontend build from builder stage
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Default directories and environment
ENV PORT=8000
ENV PROJECTS_DIR=/app/projects
EXPOSE 8000

# Run Uvicorn serving both API and Frontend
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
