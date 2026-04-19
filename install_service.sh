#!/bin/bash
# install_service.sh - installs nomad_monitor as a systemd service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PATH="/usr/local/bin/nomad_monitor.py"
SERVICE_FILE="/etc/systemd/system/nomad-monitor.service"

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash install_service.sh"
    exit 1
fi

echo "Installing nomad_monitor.py to $INSTALL_PATH..."
cp "$SCRIPT_DIR/nomad_monitor.py" "$INSTALL_PATH"
chmod 755 "$INSTALL_PATH"

echo "Creating systemd service..."
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=NOMAD Monitor Dashboard
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 $INSTALL_PATH
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Enabling and starting service..."
systemctl daemon-reload
systemctl enable nomad-monitor
systemctl start nomad-monitor

echo ""
echo "Done. Service status:"
systemctl status nomad-monitor --no-pager
echo ""
echo "Dashboard available at http://$(hostname -I | awk '{print $1}'):7070"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status nomad-monitor"
echo "  sudo systemctl stop nomad-monitor"
echo "  sudo systemctl restart nomad-monitor"
echo "  sudo journalctl -u nomad-monitor -f"
