#!/usr/bin/env bash
# Pasang / update memescan di VPS Ubuntu/Debian sebagai service systemd `memescan`.
# Mode PAPER saja. Tidak menyentuh MemeSniper (/root/memesniper) sama sekali.
#
#   curl -sL https://raw.githubusercontent.com/agilganteng/memescan/main/install-vps.sh | sudo bash
#
# Jalankan ulang perintah yang sama untuk update. Data & .env di /root/memescan/data tidak dihapus.
set -euo pipefail

DIR=/root/memescan
REPO=https://github.com/agilganteng/memescan

if [ "$(id -u)" != 0 ]; then echo "Jalankan pakai sudo/root."; exit 1; fi

echo "== 1/4 Paket sistem"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv git curl >/dev/null

echo "== 2/4 Ambil kode"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull -q --ff-only
else
  git clone -q "$REPO" "$DIR"
fi
mkdir -p "$DIR/data"
chmod 700 "$DIR/data"

echo "== 3/4 Python + websockets"
[ -x "$DIR/venv/bin/python3" ] || python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip >/dev/null
"$DIR/venv/bin/pip" install -q "websockets>=10"

if ! grep -qs '^TELEGRAM_BOT_TOKEN=.' "$DIR/data/.env" || ! grep -qs '^TELEGRAM_CHAT_ID=.' "$DIR/data/.env"; then
  echo "== Telegram"
  "$DIR/venv/bin/python3" "$DIR/memescan.py" setup --data "$DIR/data" </dev/tty
fi

echo "== 4/4 Service systemd"
cat > /etc/systemd/system/memescan.service <<UNIT
[Unit]
Description=memescan - sniper pump.fun (mode paper)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python3 -u $DIR/memescan.py --data $DIR/data
Restart=always
RestartSec=10
Nice=5
MemoryMax=400M

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q memescan
systemctl restart memescan
sleep 8
systemctl --no-pager --lines=0 status memescan | head -5 || true
journalctl -u memescan -n 15 --no-pager || true

cat <<'TXT'

memescan jalan 24 jam (mode paper, tidak pernah beli pakai uang asli).
  Log langsung : journalctl -u memescan -f
  Ringkasan    : /root/memescan/venv/bin/python3 /root/memescan/memescan.py status
  Kalibrasi    : /root/memescan/venv/bin/python3 /root/memescan/memescan.py calibrate
  Stop / start : systemctl stop memescan  /  systemctl start memescan
  Update       : jalankan ulang perintah curl tadi
TXT
