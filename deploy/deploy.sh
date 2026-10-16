#!/bin/bash
set -e

APP_DIR="/opt/awgp-audiobook"
REPO_URL="https://github.com/ashishkumarsinghh/awgp_audiobook_pipeline.git"

echo "=== AWGP Audiobook Pipeline Deploy ==="

if [ ! -d "$APP_DIR" ]; then
    echo "Cloning repository..."
    sudo git clone "$REPO_URL" "$APP_DIR"
    sudo chown -R $USER:$USER "$APP_DIR"
else
    echo "Pulling latest code..."
    cd "$APP_DIR"
    git pull origin master || true
fi

cd "$APP_DIR"

if [ ! -f ".env" ]; then
    echo "WARNING: .env file not found! Creating template .env..."
    cat << 'EOF' > .env
PORT=8000
PROJECTS_DIR=/app/projects
JOB_WORKER_ENABLED=1
FRONTEND_ORIGINS=*
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
SARVAM_API_KEY=YOUR_SARVAM_API_KEY
OCR_MODEL=gemini-3.5-flash-lite
PRONUNCIATION_FILE=configs/improved_pronunciation.json
EOF
    echo "Please update .env with your real API keys."
fi

# Ensure storage directories exist
mkdir -p projects

echo "Building and starting container with Docker Compose..."
sudo docker compose down || true
sudo docker compose up -d --build

echo "=== Deployment Complete ==="
sudo docker compose ps
