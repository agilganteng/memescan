#!/data/data/com.termux/files/usr/bin/bash
# Pasang memescan (sniper pump.fun, mode paper) di HP Android lewat Termux.
#   curl -sL https://raw.githubusercontent.com/agilganteng/memescan/main/termux-setup.sh | bash
# Jalankan ulang untuk update. Data & .env di ~/memescan/data tidak dihapus.
set -e

pkg update -y >/dev/null
pkg install -y python git >/dev/null
pip install -q "websockets>=10"

if [ -d "$HOME/memescan/.git" ]; then
  git -C "$HOME/memescan" pull -q --ff-only
else
  git clone -q https://github.com/agilganteng/memescan "$HOME/memescan"
fi
mkdir -p "$HOME/memescan/data"

if ! grep -qs '^TELEGRAM_BOT_TOKEN=.' "$HOME/memescan/data/.env" || ! grep -qs '^TELEGRAM_CHAT_ID=.' "$HOME/memescan/data/.env"; then
  python3 "$HOME/memescan/memescan.py" setup </dev/tty
fi

cat > "$HOME/memescan/run.sh" <<'RUN'
#!/data/data/com.termux/files/usr/bin/bash
# Biar Android tidak "menidurkan" Termux saat layar mati.
termux-wake-lock 2>/dev/null || true
cd "$HOME/memescan"
while true; do
  python3 -u memescan.py >> data/memescan.log 2>&1 || true
  sleep 10  # kalau crash, nyala lagi sendiri
done
RUN
chmod +x "$HOME/memescan/run.sh"

pkill -f "memescan/run.sh" 2>/dev/null || true
pkill -f "memescan.py" 2>/dev/null || true
nohup "$HOME/memescan/run.sh" >/dev/null 2>&1 &

echo
echo "memescan jalan di background (mode paper)."
echo "Log:        tail -f ~/memescan/data/memescan.log"
echo "Ringkasan:  python3 ~/memescan/memescan.py status"
echo "Matikan:    pkill -f memescan/run.sh; pkill -f memescan.py"
