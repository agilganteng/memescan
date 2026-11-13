# Praregistrasi: trading koin lulusan pump.fun di PumpSwap (paper)

Ditulis 13 Nov 2026 22:30 UTC, SEBELUM melihat hasil untung/rugi apa pun.
Yang sudah dilihat hanya hitungan data: 4.138 koin lulus, 3,38 juta baris harga
(8 Nov 08:15 UTC sampai 13 Nov 18:46 UTC), median telat deteksi 166 detik.

Kode: `riset/lulus_report.py`. Data: `riset/lulus.py` (DexScreener tiap 60 dtk sampai 6 jam,
lalu tiap 5 menit sampai 72 jam).

## Koin yang dihitung
- Semua koin yang terdeteksi lulus dan punya ≥24 jam data setelah deteksi.
- Masuk di baris harga pertama yang ≥30 detik setelah deteksi dan harganya > 0.
- Likuiditas di baris masuk itu harus ≥ $5.000.

## Biaya dan isi order
- Biaya 1,5% per sisi (fee + slippage + priority). Beli = harga × 1,015, jual = harga × 0,985.
- TP terisi di level TP kalau ada baris harga ≥ level.
- SL terisi di harga baris yang pertama tembus (bukan di level, jadi ikut gap 60 detik / 5 menit).
- Rug: kalau harga 0 selama ≥3 baris berturut-turut, atau likuiditas < $500, posisi dihitung 0x.

## Aturan keluar (6)
- H1, H6, H24: tahan 1 / 6 / 24 jam.
- X1: TP 2x, SL −30%, maks 24 jam.
- X2: TP +50%, SL −25%, maks 6 jam.
- X3: trailing 30% aktif setelah +50%, SL −40%, maks 24 jam.

## Filter (6), semua pakai data sebelum masuk saja
- L0 semua koin lulus.
- L1 rugcheck bersih: mint & freeze dicabut, tanpa risiko 'danger', top10 ≤ 30%, insider 0.
- L2 punya akun X sendiri (link DexScreener ke akun, bukan post/komunitas).
- L3 likuiditas ≥ $20.000 saat masuk.
- L4 momentum: harga saat masuk > harga saat pertama terdeteksi.
- L5 L1 + L2 (latar belakang + sosial).

Total 36 kombinasi.

## Pembagian waktu dan syarat lulus
- A = paruh pertama koin menurut waktu deteksi, B = paruh kedua.
- Lulus kalau: n_B ≥ 30, rata A > 1, rata B > 1, dan rata B tanpa koin terbaik > 1.
- Dengan 36 kombinasi, 1–2 yang lulus bisa karena kebetulan. Jadi kombinasi yang lulus
  belum dianggap terbukti sebelum diuji lagi di data baru setelah tanggal laporan ini
  (perekam jalan sampai 23 Nov).

## Simulasi modal
- Urut waktu, 10% modal per trade, stake maks 2% likuiditas saat masuk.
- Modal awal $100 / $200 / $1000.
- Batas data: Jan–Okt 2026 tidak bisa diuji, karena perekam baru mulai 8 Nov.

## Juga dilaporkan (deskriptif, bukan syarat lulus)
- Sebaran puncak harga dari titik masuk dalam 24 dan 72 jam (% yang pernah ≥2x, ≥5x, ≥10x).
- Rata-rata hasil per kelompok telat deteksi.
