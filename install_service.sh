#!/usr/bin/env bash
set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/sentinelle83.service" <<EOF
[Unit]
Description=Sentinelle83
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/.venv/bin/python $PROJECT_DIR/main.py
Restart=always
RestartSec=20

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now sentinelle83
echo "Service installé."
