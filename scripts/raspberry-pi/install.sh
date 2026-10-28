#!/usr/bin/env bash
# One-shot installer for Raspberry Pi OS (Bookworm, 64-bit recommended). Run from the repo root:
#   bash scripts/raspberry-pi/install.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
APP_USER="${SUDO_USER:-$USER}"

echo "==> Installing system packages"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git curl nginx

if ! command -v node >/dev/null 2>&1; then
  echo "==> Installing Node.js 20 + yarn"
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
sudo npm install -g yarn

if ! command -v mongod >/dev/null 2>&1 && ! sudo docker ps >/dev/null 2>&1; then
  echo "==> Installing MongoDB via Docker (Pi 4: mongo:4.4.18, Pi 5: mongo:7)"
  curl -fsSL https://get.docker.com | sudo sh
  if grep -q "Raspberry Pi 5" /proc/device-tree/model 2>/dev/null; then IMG=mongo:7; else IMG=mongo:4.4.18; fi
  sudo docker run -d --name mongo --restart unless-stopped -p 127.0.0.1:27017:27017 -v mongo-data:/data/db "$IMG"
fi

echo "==> Granting $APP_USER access to serial ports (dialout group)"
sudo usermod -aG dialout "$APP_USER"

echo "==> Backend virtualenv"
cd "$APP_DIR/backend"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install fastapi "uvicorn[standard]" python-socketio motor python-dotenv asyncua msgpack pyserial pydantic
[ -f .env ] || cp .env.example .env

echo "==> Building frontend"
cd "$APP_DIR/frontend"
[ -f .env ] || echo "REACT_APP_BACKEND_URL=" > .env
yarn install
yarn build

echo "==> Installing systemd service + nginx site"
sed -e "s#__APP_DIR__#$APP_DIR#g" -e "s#__APP_USER__#$APP_USER#g" "$APP_DIR/scripts/raspberry-pi/opcua-stream.service" | sudo tee /etc/systemd/system/opcua-stream.service >/dev/null
sed -e "s#__APP_DIR__#$APP_DIR#g" "$APP_DIR/scripts/raspberry-pi/nginx-opcua-stream.conf" | sudo tee /etc/nginx/sites-available/opcua-stream >/dev/null
sudo ln -sf /etc/nginx/sites-available/opcua-stream /etc/nginx/sites-enabled/opcua-stream
sudo rm -f /etc/nginx/sites-enabled/default
sudo chmod o+x "$HOME" || true
sudo systemctl daemon-reload
sudo systemctl enable --now opcua-stream
sudo systemctl restart nginx

cat <<EOF

Done. Open http://$(hostname -I | awk '{print $1}')/ from any browser on your network.
If you use the GPIO UART (/dev/serial0): run 'sudo raspi-config' -> Interface Options -> Serial Port
  -> login shell over serial: NO, serial hardware: YES, then reboot.
Log out/in (or reboot) once so the dialout group membership takes effect.
EOF
