# memescan

Screener memecoin yang scan coin trending/baru di DexScreener tiap beberapa menit, kasih skor momentum + red flag risiko, lalu kirim **beberapa** kandidat sekaligus ke Telegram.

## Cara jalan

1. Butuh Python 3.9+ saja, tidak perlu install library.
2. Coba sekali dulu: `python3 memescan.py`
3. Untuk notifikasi Telegram:
   - Chat ke **@BotFather** di Telegram, ketik `/newbot`, simpan token-nya.
   - Kirim pesan apa saja ke bot kamu, lalu buka `https://api.telegram.org/bot<TOKEN>/getUpdates` dan ambil angka `chat.id`.
   - Jalankan:
     ```
     export TELEGRAM_BOT_TOKEN=123:abc
     export TELEGRAM_CHAT_ID=123456789
     python3 memescan.py --loop 300
     ```

## Yang dicek

| Sinyal positif | Red flag / ditolak |
|---|---|
| Harga naik 5m & 1j | Likuiditas < $15K (ditolak) |
| Volume 1j tinggi dibanding likuiditas | Volume 1j < $20K (ditolak) |
| Mayoritas transaksi beli | Umur > 72 jam (ditolak) |
| Umur 1–24 jam | Mint/freeze authority masih aktif di RugCheck (ditolak) |
| Likuiditas sehat vs market cap | Lagi dump, jual mendominasi, sudah naik >1000% (risiko pucuk) |

Untuk kandidat teratas, script juga ambil candle 5 menit dari GeckoTerminal dan cek EMA9 vs EMA21 (tren), RSI 14 (overbought di atas 85), dan lonjakan volume candle terakhir. Matikan dengan `--no-ta`.

Coin yang sudah dikirim tidak dikirim ulang selama 6 jam (`seen.json`).

## Paper trading (uang bohongan)

Setiap sinyal otomatis "dibeli" $10 dari saldo bohongan $100, dengan TP +50% dan SL -25%. Tiap scan, posisi dicek pakai high/low candle 5 menit sejak scan terakhir (jadi TP/SL yang kesentuh di antara dua scan tetap tercatat; kalau dua-duanya kena di candle yang sama, dianggap SL) dan ditutup kalau kena TP, SL, lewat 24 jam, atau likuiditasnya ditarik (dianggap rug, -100%). Biaya + slippage diasumsikan 3% per sisi. Hasil menang/kalah dan saldo dikirim ke Telegram. Saldo dan posisi terbuka disimpan di `seen.json`, yang di GitHub Actions dibawa antar run lewat cache.

Tujuannya buat buktiin dulu sinyal ini menghasilkan atau tidak, sebelum pakai uang asli. Ubah dengan `--stake`, `--paper-start`, `--tp-pct`, `--sl-pct`, `--max-hold-h`, `--cost-pct`, atau matikan dengan `--no-paper`.

## Atur ambang

```
python3 memescan.py --loop 300 --min-liq 30000 --min-score 60 --top 3 --chain solana
```
Chain lain: `base`, `bsc`, `ethereum` (RugCheck hanya untuk Solana).

## Penting

Ini **sinyal, bukan saran beli**. Skor tinggi artinya "lagi ramai dan tidak ada red flag yang kelihatan", bukan "pasti naik". Mayoritas memecoin baru jatuh ke nol, dan rug pull bisa lolos semua cek otomatis. Pakai uang yang siap hilang.
