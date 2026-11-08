# Praregistrasi: callout gratis + cek latar belakang (ditulis 8 Nov 2026, SEBELUM ada data)

Sumber callout: channel Telegram publik (t.me/s, ditemukan otomatis), dan akun X caller lewat mirror publik kalau probe-nya jalan. Grup Telegram privat hanya kalau user join sendiri.

Simulasi:
- Beli di harga DexScreener pertama yang tercatat ≥30 detik setelah callout terdeteksi. Pembacaan tiap ~90 detik, harga tiap ~60 detik.
- Biaya 1,5% per sisi.
- Kalau pool hilang atau harganya 0, trade dianggap rugi total.
- Stop dicek di sampel 60 detik berikutnya, jadi gap turun ikut terhitung.

Filter (semua pakai info yang sudah ada saat masuk):
- F0: semua call.
- F1: koin di-call ≥2 channel berbeda; masuk saat call channel ke-2.
- F2: rugcheck bersih. Mint/freeze authority dicabut, tidak ada risiko 'danger', top10 ≤30%, insider/cluster = 0. Cek ini meniru Soul Scanner / SolSniffer / Bubblemaps.
- F3: akun X sendiri (bukan link status/komunitas) dengan follower ≥1.000 dan umur ≥30 hari.
- F4: likuiditas ≥$10k, mcap $20k–$5M.
- F5: punya X + website.
- F6: F2 + F3 + F4, yaitu "screening penuh".
- F7: F1 + F2 + F4.
- F8: call pertama untuk koin itu.
- F9: call telat, ≥30 menit setelah call pertama.

Exit:
- H1, H6, H24: tahan 1, 6, atau 24 jam.
- X1: TP 2x / SL 30%.
- X2: jual ½ di 2x, sisanya trailing 30%.
- X3: trailing 30% setelah +50%, SL 40%.
- X4: TP +50% / SL 25%, maks 6 jam.

Split waktu: separuh call pertama (A) vs separuh berikutnya (B).

Syarat lulus (semua harus terpenuhi):
- n di B ≥30.
- Rata-rata A >1,0.
- Rata-rata B >1,0.
- Rata-rata B tanpa koin terbaik >1,0.

Pembanding: 70 kombinasi (10 filter × 7 exit). Kalau cuma 1–3 yang lulus, itu masih mungkin kebetulan, jadi wajib dicek ulang di data minggu berikutnya.

Simulasi modal $100/$200/$1000 dengan 10% per trade, urut waktu. Data hanya mulai 8 Nov 2026; Jan–Okt 2026 tidak bisa diuji karena channel tidak menyimpan harga lama.

## Tambahan 8 Nov 2026 14:31 UTC (permintaan user, ditulis SEBELUM melihat hasil)

Penilaian utama sekarang memakai urutan tiga lapis. Filter lain (F1, F4, F8, F9, filter ala memescan) hanya jadi pembanding.

1. **Callout** sebagai pemicu. Sumbernya:
   - channel Telegram publik (recorder GitHub)
   - grup Telegram yang di-join
   - GMGN Callout Radar (GMGN + fomo + pump + X)
2. **Latar belakang koin** sebagai filter wajib. Pakai rugcheck yang meniru Soul Scanner / SolSniffer / Bubblemaps:
   - mint dan freeze authority sudah dicabut
   - tidak ada risiko 'danger'
   - top10 ≤30%
   - insider/cluster = 0
   - ditambah likuiditas ≥$10k
3. **Narasi sosmed** sebagai filter wajib. Koin punya akun X sendiri (bukan link status/komunitas) dengan follower ≥1.000 dan umur akun ≥30 hari, ATAU punya X + website.
   Batasnya: isi post X tidak bisa dibaca dari server (mirror mati). Jadi "narasi" diukur dari akun/website koin, bukan jumlah mention.

Nama gabungan ini **P3 = callout → latar belakang → sosmed**. Exit dan syarat lulusnya sama dengan di atas: n di B ≥30, rata A >1, rata B >1, rata B tanpa koin terbaik >1.

Kalau P3 tidak mencapai n ≥30, hasilnya dilaporkan "belum cukup data", bukan lulus atau gagal.

### Tambahan 8 Nov 2026 14:55 UTC: narasi dari akun lain (permintaan user, SEBELUM hasil)

Lapis 3 (sosmed) diperluas. Koin lolos kalau memenuhi **salah satu** syarat:
- (a) punya akun X sendiri, sesuai aturan di atas; atau
- (b) **ramai di X dari akun lain**, diukur SEBELUM waktu masuk, pakai pencarian X di Chrome user, tab Latest, dengan operator since_time/until_time:
  - ≥5 post yang menyebut CA atau $TICKER dalam 60 menit sebelum masuk, dari ≥3 akun berbeda; ATAU
  - ≥1 akun dengan follower ≥10.000 menyebut koin itu dalam 6 jam sebelum masuk.

Pencarian X dilakukan belakangan (retroaktif) dengan batas waktu sebelum masuk, jadi tidak mengintip masa depan. Tempo dibuat pelan supaya akun user tidak kena limit.

Varian yang dilaporkan:
- P3a = callout + latar belakang + (a)
- P3b = callout + latar belakang + (b)
- P3 = callout + latar belakang + (a atau b) → **utama**
