#!/data/data/com.termux/files/usr/bin/bash
# Pasang memescan di HP Android (Termux), scan tiap 60 detik.
# Jalankan di Termux:
#   curl -sL https://raw.githubusercontent.com/agilganteng/memescan/main/termux-setup.sh | bash
set -e

pkg update -y >/dev/null
pkg install -y python git >/dev/null

if [ -d "$HOME/memescan" ]; then
  git -C "$HOME/memescan" pull -q
else
  git clone -q https://github.com/agilganteng/memescan "$HOME/memescan"
fi

ENV="$HOME/memescan/.env"
if [ ! -f "$ENV" ]; then
  printf "Tempel TELEGRAM_BOT_TOKEN dari BotFather lalu Enter: "
  read -r TOKEN < /dev/tty
  echo "export TELEGRAM_BOT_TOKEN='$TOKEN'" > "$ENV"
  chmod 600 "$ENV"
fi

cat > "$HOME/memescan/run.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Biar Android tidak "menidurkan" Termux saat layar mati.
termux-wake-lock 2>/dev/null || true
cd "$HOME/memescan"
. ./.env
while true; do
  python3 memescan.py --loop 60 --state seen.json >> scan.log 2>&1 || true
  sleep 10  # kalau crash, nyala lagi sendiri
done
EOF
chmod +x "$HOME/memescan/run.sh"

pkill -f "memescan/run.sh" 2>/dev/null || true
nohup "$HOME/memescan/run.sh" >/dev/null 2>&1 &

echo
echo "memescan jalan di background, scan tiap 60 detik."
echo "Lihat log:   tail -f ~/memescan/scan.log"
echo "Matikan:     pkill -f memescan/run.sh"
echo "Nyalakan:    nohup ~/memescan/run.sh >/dev/null 2>&1 &"
