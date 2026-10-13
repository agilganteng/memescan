# memescan

Sniper memecoin pump.fun (Solana) dengan aturan yang sama seperti MemeSniper. **Mode paper saja**: tidak ada private key, tidak ada transaksi asli. Notifikasi ke Telegram.

## Pasang di VPS (jalan 24 jam)

Login ke VPS sebagai root, lalu:

```
curl -sL https://raw.githubusercontent.com/agilganteng/memescan/main/install-vps.sh | sudo bash
```

Script akan minta:
- token bot Telegram (dari @BotFather → /mybots → pilih bot → API Token);
- URL websocket RPC (opsional, misal `wss://mainnet.helius-rpc.com/?api-key=...`). Enter saja untuk pakai RPC publik Solana.

Keduanya tidak tampil di layar dan disimpan di `/root/memescan/data/.env` (chmod 600, tidak pernah di-commit). Chat ID dicari otomatis dari /start ke bot. Bisa juga diisi langsung: `curl ... | sudo TELEGRAM_CHAT_ID=123 bash`.

Hasilnya service systemd `memescan`, terpisah dari `memesniper`.

| Perintah | Fungsi |
|---|---|
| `journalctl -u memescan -f` | log langsung |
| `/root/memescan/venv/bin/python3 /root/memescan/memescan.py status` | ringkasan winrate & saldo paper |
| `/root/memescan/venv/bin/python3 /root/memescan/memescan.py calibrate` | latih skor + uji ambang |
| `systemctl stop memescan` / `start` | matikan / nyalakan |

Update: jalankan ulang perintah `curl` di atas.

HP Android (Termux): `curl -sL https://raw.githubusercontent.com/agilganteng/memescan/main/termux-setup.sh | bash`.

## Cara kerja

1. Baca langsung semua transaksi program pump.fun dari RPC Solana (websocket `logsSubscribe`): koin baru dan setiap beli/jual sejak detik pertama. Gratis lewat RPC publik, atau pakai RPC Helius kamu supaya lebih stabil.
2. **Gate cepat**, umur 6–60 detik, cek tiap 1,5 detik: inflow ≥1 SOL, harga ≥1,05x dari awal, market cap ≤150 SOL, turun dari puncak ≤20%.
3. **Gate lambat** untuk koin yang naik pelan, cek tiap 15 detik sampai umur 30 menit: dalam 180 detik terakhir harga ≥1,5x dan inflow ≥2,5 SOL, likuiditas ≥12 SOL, turun dari puncak ≤10%.
4. **Filter holder**, dicek lagi 5 detik kemudian: ≥5 holder, top10 ≤35%, top20 ≤50%, dev ≤10%. Kalau dev sudah jual semua, ditolak.
5. Lolos semua → **kandidat**: dicatat dengan 18 fitur, dikirim ke Telegram, dan diberi *shadow trade* 0,5 SOL untuk mengukur hasilnya.
6. **Aturan jual**: 50% dijual di 2x, sisanya trailing 45% dari puncak (35% setelah 6x). SL −35%. Time stop 10 menit kalau belum pernah 1,3x. Koin tanpa trade 20 menit dianggap basi.
7. **Simulasi realistis**: setiap order diisi 3 detik setelah keputusan, di harga kurva bonding saat itu, plus slippage 2%, fee pump.fun 1,25%, dan priority fee 0,0005 SOL.

## Skor dan ukuran posisi

- Skor 0–100% adalah peluang kena TP 2x, dari regresi logistik yang dilatih dengan `calibrate`. Butuh ≥100 kandidat berlabel.
- Data dibagi berdasarkan waktu: 70% paling lama untuk melatih, 30% terbaru untuk menguji (hold-out).
- Ambang mengikuti spesifikasi: skor ≥60% all-in, 50–60% setengah saldo, di bawah itu skip. Ambang **hanya aktif kalau terbukti di hold-out**: ≥30 trade di rentang itu dan batas bawah CI 95% rata-rata hasil > 1,00x.
- Selama belum terbukti (`SCORE_ALLIN_MIN` / `SCORE_HALF_MIN` kosong), saldo paper tidak dipakai. Kandidat cuma dicatat + shadow trade.
- Satu posisi sekaligus, koin yang sama tidak pernah dibeli ulang. Saldo paper mulai 0,5 SOL. Auto-stop di bawah 0,1 SOL, lanjutkan dengan `--resume`.
- `calibrate` juga membuat simulasi modal $200 di data hold-out (PnL + winrate). Data sebelum memescan jalan tidak ada, jadi periode Jan 2026 – sekarang tidak bisa disimulasikan.

## Telegram

- 🎯 kandidat baru (maksimal 30 per jam, sisanya tetap dicatat)
- ✅/❌ hasil shadow trade dan trade paper
- 📊 ringkasan tiap 6 jam: jumlah trade, winrate dengan CI 95%, rata-rata hasil, saldo paper

## Atur angka

Semua angka bisa diubah di `data/.env` (nama variabel lihat `DEFAULTS` di `memescan.py`), lalu `systemctl restart memescan`. Jangan isi `SCORE_ALLIN_MIN` manual: biarkan `calibrate` yang mengisi kalau terbukti.

## Batasan yang perlu diketahui

- Holder dihitung dari beli/jual di kurva bonding. Token yang dipindah antar wallet di luar pump.fun tidak terlihat.
- RPC publik Solana bisa putus atau membatasi; bot sambung ulang sendiri. Kalau sering putus, isi `RPC_WS_URL` dengan RPC Helius dan pantau pemakaian kreditnya di dashboard Helius.
- Koin pump.fun dengan quote selain SOL dilewati.
- Riwayat dev (berapa koin dan rug sebelumnya) hanya sejak bot pertama jalan.
- Mint/freeze authority tidak dicek karena selalu dicabut untuk koin di kurva bonding pump.fun.
- Ini sinyal untuk riset, bukan saran beli. Riset MemeSniper sebelumnya menemukan semua strategi yang diuji rugi di data out-of-sample.

## Versi lama

Screener DexScreener yang lama ada di `legacy/screener.py` (tidak dipakai lagi).
