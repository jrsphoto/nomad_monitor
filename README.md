# nomad_monitor

A lightweight real-time dashboard for monitoring GPU, CPU, and Ollama performance on a [Project N.O.M.A.D.](https://github.com/Crosstalk-Solutions/project-nomad) system.

Runs as a small web server on your NOMAD machine. Open it in any browser on your network.

![Dashboard shows GPU utilization, VRAM usage, CPU load, and Ollama model stats]

## What it shows

- GPU utilization, temperature, power draw, SM and memory clocks
- VRAM used/total with 90-second history sparkline
- CPU utilization with 90-second history sparkline
- System RAM usage
- All loaded Ollama models with size, VRAM vs RAM split, quantization, context length
- Layer offload status (how many layers are on GPU vs CPU)
- KV cache size
- Last query generation speed (tokens/sec)

## Requirements

- Linux (reads from `/proc/stat` and `/proc/meminfo`)
- Python 3.6+
- NVIDIA GPU with `nvidia-smi` available
- Docker with a running `nomad_ollama` container
- Ollama API accessible at `localhost:11434`

No pip installs required. Uses only Python standard library.

## Usage

Copy `nomad_monitor.py` to your NOMAD machine and run it:

```bash
sudo python3 nomad_monitor.py
```

Then open a browser and navigate to:

```
http://YOUR_MACHINE_IP:7070
```

The dashboard updates every second. Run it in a `screen` or `tmux` session if you want it to persist after closing your SSH session:

```bash
screen -S monitor
sudo python3 nomad_monitor.py
# Ctrl+A then D to detach
```

To stop it:

```bash
sudo pkill -f nomad_monitor.py
```

## Running as a service

To have the dashboard start automatically on boot, use the included install script:

```bash
sudo bash install_service.sh
```

This installs nomad_monitor as a systemd service that starts automatically with the system and restarts if it crashes.

Useful commands once installed as a service:

```bash
sudo systemctl status nomad-monitor
sudo systemctl stop nomad-monitor
sudo systemctl restart nomad-monitor
sudo journalctl -u nomad-monitor -f   # view logs
```

To remove the service:

```bash
sudo bash uninstall_service.sh
```

## Configuration

Two variables at the top of the script if you need to change them:

```python
OLLAMA_API = "http://localhost:11434"  # Ollama API address
PORT = 7070                             # Port the dashboard listens on
```

## Notes

- Needs to run as root (or a user with Docker access) to read the Ollama container logs
- The layer offload and tokens/sec stats are pulled from the `nomad_ollama` Docker container logs -- if your container has a different name, update the `get_layer_stats()` function
- Tokens/sec reflects the most recently completed query, not a live rate
- While written for NOMAD, it will work with any Ollama setup running in a Docker container named `nomad_ollama`

## License

MIT
