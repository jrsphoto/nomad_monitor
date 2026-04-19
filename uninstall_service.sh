#!/bin/bash
# uninstall_service.sh - removes the nomad-monitor systemd service

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash uninstall_service.sh"
    exit 1
fi

echo "Stopping and disabling nomad-monitor service..."
systemctl stop nomad-monitor 2>/dev/null || true
systemctl disable nomad-monitor 2>/dev/null || true

echo "Removing service files..."
rm -f /etc/systemd/system/nomad-monitor.service
rm -f /usr/local/bin/nomad_monitor.py

systemctl daemon-reload

echo "Done. nomad-monitor service removed."
