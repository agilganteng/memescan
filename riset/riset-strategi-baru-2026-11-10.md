# Daftar pra-registrasi, ditulis sebelum hasil

Keluarga strategi baru. PAPER. Daftar di bawah dikunci sebelum cache dibaca.

Target pembanding, tidak disetel ulang: aturan (b) + gerbang jam lahir 12–16 UTC.
Entri aturan (b): umur 120, jeda 3–8, growth>=3, beli>=0,65, vol>=3, laju>=1,5,
jual parsial 50% di 2x sisa TP5 SL0,7 600 dtk.
Gerbang: jeda 0,4, syarat (b) plus drawdown<=0,35 dan jam UTC [12,16), jual TP5 SL0,7 1800 dtk.

Protokol, dikunci di sini:
- Setel hanya di A (t0 < 2 Nov 2026 17:43 UTC). Di tiap keluarga, ambil satu konfigurasi
  dengan n_A>=30, rata A>1, dan A tanpa koin terbaik >1. Pilihan = rata A tertinggi.
- B (sampai 5 Nov 2026 16:55 UTC) diuji sekali pada pilihan itu. Lulus B: n_B>=30,
  rata B>1, B tanpa koin terbaik >1.
- C tercemar, hanya dilaporkan. t0 sesudah 10 Nov 2026 07:17 UTC tidak masuk A, tidak masuk B,
  tidak memilih. Kalau ada, itu irisan konfirmasi, termasuk untuk gerbang lama.
- Null 20x mengacak urutan hasil di dalam tiap konfigurasi, periode koin tetap.
  Bonferroni 0,05 / jumlah konfigurasi pada uji B pilihan.
- Biaya sama dengan riset sebelumnya: fee 1,25%/sisi, slip 2%/sisi, priority 0,0005 SOL,
  ukuran 0,1 SOL, stop candle x0,72.
- Mengalahkan gerbang hanya jika lulus protokol dan rata B serta B tanpa terbaik
  keduanya lebih tinggi dari gerbang yang dihitung ulang di run ini.
- LAYAK hanya jika itu terjadi dan irisan segar juga lolos (n>=30, rata>1, tanpa terbaik >1).
  Tanpa koin segar, vonis paling tinggi BELUM LAYAK.

Keluarga, ambang tidak digeser setelah hasil:
F1 Exit pada entri (b) saja, jeda dan filter (b) tetap. Jual: parsial baseline;
waktu 120/300/600/1800 SL0,7 tanpa TP; parsial 2x sisa TP3 600 dan 1800;
parsial 2x sisa TP5 1800; parsial 3x sisa TP5 600 dan 1800; trail +50% lebar 20% 600 dan 1800;
trail +50% lebar 30% 1800; trail +100% lebar 30% 1800; moonbag 70% di 2x dan di 3x, sisa trail 30%.
Transfer: jual pemenang F1 dipasang ke entri gerbang. Bukan pencarian jual di gerbang.
F2 Gelombang kedua. Sesudah detik 120 harga menyentuh 2x atau 3x dari jangkar, lalu turun 20% atau 35%
dari puncak, lalu reclaim: kembali ke harga detik 120, atau ke 90% puncak sebelum turun.
Di dalam satu candle puncak diperbarui dari high dulu, baru cek turun. Reclaim hanya di candle berikut.
Jeda 3–8. Jual: parsial baseline, TP2 SL0,7 600, trail +50% lebar 30% 1800.
F3 Dev/pembuat, bukan snipe 0,4 dtk yang sudah gagal. Umur 60 dan 120, jeda 3–8, jual parsial.
Dev beli (0, 0,5) SOL atau [0,5, 2) SOL, dev belum jual, belum pernah rug.
Tambahan di umur 120: dev_pct<=5% dan token pertama; atau dev_pct<=10% dan belum rug.
F4 Ukuran trade dan pertumbuhan pembeli. Tape wallet hanya sampai 5 menit; kalau cakupan
lebih pendek dari umur keputusan, aturan ini gagal tertutup.
Banyak kecil: beli>=20, median<=0,5 SOL, beli terbesar<=25% total, unik>=15.
Sedikit besar: beli 5–15, median>=1 SOL, terbesar>=30% (kontras, bukan harapan untung).
Pertumbuhan unik 120-60 >=10 dan laju pembeli>=1. Gabungan banyak-kecil + pertumbuhan.
Umur 60: unik 60-30>=8, beli>=12, median<=0,5.
F5 Tanpa tekanan jual. Jendela (60,120] atau (30,60]: nol jual dan beli cukup, atau SOL jual <=10%
dan drawdown<=0,35. Gagal tertutup kalau tidak ada volume di jendela.
F6 Jam dan hari untuk aturan LAIN, dipilih di A. Bukan mengulang jam 12–16 pada aturan (b).
Blok jam 0–6, 6–12, 12–18, 18–24 UTC. Hari: semua, hari kerja, akhir pekan.
Dasarnya mom120 dan dev-beli [0,5, 2) umur 120. Kalender data hanya sekitar dua minggu.
F7 Momentum dekat lulus, bukan grid 50–98% dan bukan kontrol 92%. Kurva 70/80/90%,
sinyal pertama pada umur >=120 dtk, harga >=1,5x harga 60 dtk sebelumnya, jeda 3–8.
Jual TP2 SL0,7 600 atau trail +50% lebar 20% SL0,7 600.
F8 Aturan (b) plus gerbang anti-rug. growth<2 TIDAK dipakai karena bertentangan dengan (b).
P1: top10<=30%, dev<=5%, belum jual, belum rug, bundle<5, bukan proksi fresh, drawdown<=40%.
P2: top10<=35%, dev<=10%, belum jual, belum rug, bundle<5, drawdown<=50%.
Proksi fresh: unik>=20, holder<=8, unik/holder>=3. Bundle = pembeli non-dev pada detik pertama.
Satu baris tambahan: entri gerbang 12–16 yang juga lolos P1, jual gerbang tetap.
Anti-honeypot tidak diuji.

# Vonis

TIDAK LAYAK. Tidak ada keluarga baru yang lolos protokol dan mengalahkan gerbang (b)+jam 12-16. Konfigurasi 80. Lulus A+B 8. Null maks 5. Bonferroni 0.000625.

# Keluarga baru dibanding gerbang (b)+jam 12–16, 10 Nov 2026, PAPER

Anti-honeypot tidak diuji. Narasi X tidak diukur.
sha skrip cffb6f8517ac95c2bcb93e9e7161ca7abaa0e2b36388d174660b24eee780c55a. Cache `memescan-data-42685043176`.
Koin standar 135797. t0 1793059202.2 .. 1794295050.1. Koin segar 0.
Konfigurasi 80. Lulus A dan B 8. Null: 3, 3, 3, 5, 4, 2, 1, 1, 1, 3, 3, 4, 3, 1, 4, 3, 2, 4, 1, 4. Maks 5. Bonferroni 0.000625.
Angka gerbang di tabel ini dihitung ulang di run yang sama, bukan disalin dari laporan lama.

## Perbandingan

A memilih. B menguji sekali. C tercemar. Segar hanya kalau t0 sesudah 10 Nov 07:17 UTC.

| Strategi | Irisan | n | Rata | Menang (Wilson) | Tanpa terbaik | $200 8%m1 / DD | 8%m5 / DD | 10%m1 / DD | 10%m5 / DD |
|---|---|---:|---:|---|---:|---|---|---|---|
| Gerbang lama: (b)+jam 12-16 UTC | | | | | | | | | |
| | A | 103 | 1,317x | 56,3% [46,7%–65,5%] | 1,284x | $1161 / DD 18,9% | $1813 / DD 16,6% | $1658 / DD 23,1% | $2827 / DD 20,6% |
| | B | 31 | 1,229x | 58,1% [40,8%–73,6%] | 1,115x | $329 / DD 13,8% | $324 / DD 16,3% | $365 / DD 17,1% | $357 / DD 20,1% |
| | C | 38 | 1,000x | 26,3% [15,0%–42,0%] | 0,902x | $175 / DD 44,1% | $175 / DD 44,1% | $163 / DD 52,0% | $163 / DD 52,0% |
| | segar | 0 | — | — | — | — | — | — | — |
| Aturan (b) tanpa jam | | | | | | | | | |
| | A | 234 | 1,070x | 50,9% [44,5%–57,2%] | 1,060x | $359 / DD 41,9% | $507 / DD 33,2% | $380 / DD 51,0% | $574 / DD 39,9% |
| | B | 51 | 1,097x | 49,0% [35,9%–62,3%] | 1,054x | $274 / DD 35,6% | $270 / DD 37,5% | $289 / DD 42,6% | $283 / DD 44,6% |
| | C | 130 | 1,014x | 42,3% [34,2%–50,9%] | 0,996x | $127 / DD 54,2% | $183 / DD 50,5% | $106 / DD 63,9% | $167 / DD 58,8% |
| | segar | 0 | — | — | — | — | — | — | — |
| F1 pilihan A: parsial 50% 3x sisa TP5 SL0.7 600s | | | | | | | | | |
| | A | 234 | 1,091x | 48,3% [42,0%–54,7%] | 1,080x | $479 / DD 38,5% | $687 / DD 38,5% | $532 / DD 45,7% | $816 / DD 45,7% |
| | B | 51 | 1,131x | 45,1% [32,3%–58,6%] | 1,080x | $304 / DD 33,3% | $300 / DD 35,2% | $327 / DD 40,0% | $321 / DD 42,1% |
| | C | 130 | 1,045x | 40,8% [32,7%–49,4%] | 1,025x | $160 / DD 52,7% | $239 / DD 50,1% | $140 / DD 61,5% | $229 / DD 58,8% |
| | segar | 0 | — | — | — | — | — | — | — |
| F2 terbaik A, tidak lolos syarat A: pump 2x turun 20% reclaim peak90 / parsial 50% 2x sisa TP5 SL0.7 600s | | | | | | | | | | |
| | A | 1745 | 0,782x | 25,4% [23,4%–27,5%] | 0,781x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 705 | 0,767x | 25,4% [22,3%–28,7%] | 0,764x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | C | 1062 | 0,826x | 28,9% [26,3%–31,7%] | 0,824x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| F3 terbaik A, tidak lolos syarat A: umur 60 dev beli [0.5, 2) belum jual belum rug | | | | | | | | | |
| | A | 265 | 0,926x | 16,6% [12,6%–21,6%] | 0,917x | $54 / DD 80,4% | $38 / DD 85,7% | $38 / DD 87,2% | $24 / DD 91,4% |
| | B | 61 | 0,880x | 16,4% [9,2%–27,6%] | 0,863x | $111 / DD 48,2% | $110 / DD 48,1% | $95 / DD 56,2% | $94 / DD 56,1% |
| | C | 69 | 0,839x | 11,6% [6,0%–21,2%] | 0,821x | $85 / DD 58,9% | $80 / DD 61,1% | $68 / DD 67,2% | $63 / DD 69,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| F4 terbaik A, tidak lolos syarat A: sedikit besar umur 120 | | | | | | | | | |
| | A | 338 | 0,849x | 3,3% [1,8%–5,7%] | 0,846x | $6 / DD 96,9% | $3 / DD 98,4% | $3 / DD 98,7% | $1 / DD 99,4% |
| | B | 212 | 0,859x | 3,8% [1,9%–7,3%] | 0,858x | $32 / DD 84,1% | $18 / DD 91,1% | $20 / DD 90,0% | $10 / DD 95,2% |
| | C | 232 | 0,869x | 3,0% [1,5%–6,1%] | 0,866x | $33 / DD 83,4% | $17 / DD 91,4% | $21 / DD 89,5% | $9 / DD 95,4% |
| | segar | 0 | — | — | — | — | — | — | — |
| F5 terbaik A, tidak lolos syarat A: nol jual (30,60] beli>=4 | | | | | | | | | |
| | A | 739 | 0,814x | 7,2% [5,5%–9,3%] | 0,810x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 301 | 0,813x | 8,0% [5,4%–11,6%] | 0,808x | $7 / DD 96,4% | $2 / DD 99,0% | $3 / DD 98,5% | $1 / DD 99,5% |
| | C | 388 | 0,891x | 9,3% [6,8%–12,6%] | 0,843x | $11 / DD 94,7% | $3 / DD 98,5% | $4 / DD 97,8% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| F6 pilihan A: mom120 jam 12-18 hari kerja | | | | | | | | | |
| | A | 57 | 1,100x | 43,9% [31,8%–56,7%] | 1,062x | $268 / DD 30,6% | $284 / DD 18,9% | $281 / DD 37,2% | $301 / DD 24,2% |
| | B | 26 | 0,946x | 30,8% [16,5%–50,0%] | 0,885x | $179 / DD 19,1% | $174 / DD 18,1% | $172 / DD 23,6% | $167 / DD 22,5% |
| | C | 47 | 1,007x | 31,9% [20,4%–46,2%] | 0,958x | $287 / DD 22,8% | $184 / DD 43,2% | $306 / DD 27,9% | $175 / DD 51,3% |
| | segar | 0 | — | — | — | — | — | — | — |
| F7 terbaik A, tidak lolos syarat A: kurva 80% umur>=120 momentum 1.5x / TP2 SL0.7 600s | | | | | | | | | | |
| | A | 212 | 0,902x | 45,3% [38,7%–52,0%] | 0,897x | $51 / DD 75,4% | $35 / DD 83,3% | $36 / DD 83,0% | $22 / DD 89,6% |
| | B | 81 | 0,872x | 38,3% [28,4%–49,2%] | 0,864x | $96 / DD 52,0% | $85 / DD 57,6% | $79 / DD 60,4% | $68 / DD 66,1% |
| | C | 160 | 0,917x | 48,8% [41,1%–56,4%] | 0,911x | $84 / DD 63,6% | $65 / DD 71,7% | $67 / DD 72,1% | $49 / DD 79,7% |
| | segar | 0 | — | — | — | — | — | — | — |
| F8 tidak ada n_A cukup: (b) + P1 jeda 3-8 | | | | | | | | | |
| | A | 0 | — | — | — | — | — | — | — |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| Transfer jual F1 ke entri gerbang | | | | | | | | | |
| | A | 103 | 1,227x | 55,3% [45,7%–64,6%] | 1,203x | $767 / DD 20,3% | $1002 / DD 16,6% | $1012 / DD 24,8% | $1395 / DD 20,6% |
| | B | 31 | 1,218x | 58,1% [40,8%–73,6%] | 1,135x | $324 / DD 14,1% | $320 / DD 16,6% | $359 / DD 17,4% | $352 / DD 20,4% |
| | C | 38 | 0,926x | 26,3% [15,0%–42,0%] | 0,851x | $146 / DD 44,1% | $146 / DD 44,1% | $131 / DD 52,0% | $131 / DD 52,0% |
| | segar | 0 | — | — | — | — | — | — | — |

## Pilihan tiap keluarga

- F1 (pilihan A): parsial 50% 3x sisa TP5 SL0.7 600s
  A n=234 rata 1,091x tanpa terbaik 1,080x. B n=51 rata 1,131x tanpa terbaik 1,080x menang 45,1%. p B 0.14731.
  Mengalahkan gerbang dan lolos protokol: tidak.
- F2 (terbaik A, tidak lolos syarat A): pump 2x turun 20% reclaim peak90 | parsial 50% 2x sisa TP5 SL0.7 600s
  A n=1745 rata 0,782x tanpa terbaik 0,781x. B n=705 rata 0,767x tanpa terbaik 0,764x menang 25,4%. p B None.
- F3 (terbaik A, tidak lolos syarat A): umur 60 dev beli [0.5, 2) belum jual belum rug
  A n=265 rata 0,926x tanpa terbaik 0,917x. B n=61 rata 0,880x tanpa terbaik 0,863x menang 16,4%. p B None.
- F4 (terbaik A, tidak lolos syarat A): sedikit besar umur 120
  A n=338 rata 0,849x tanpa terbaik 0,846x. B n=212 rata 0,859x tanpa terbaik 0,858x menang 3,8%. p B None.
- F5 (terbaik A, tidak lolos syarat A): nol jual (30,60] beli>=4
  A n=739 rata 0,814x tanpa terbaik 0,810x. B n=301 rata 0,813x tanpa terbaik 0,808x menang 8,0%. p B None.
- F6 (pilihan A): mom120 jam 12-18 hari kerja
  A n=57 rata 1,100x tanpa terbaik 1,062x. B n=26 rata 0,946x tanpa terbaik 0,885x menang 30,8%. p B 0.67895.
  Mengalahkan gerbang dan lolos protokol: tidak.
- F7 (terbaik A, tidak lolos syarat A): kurva 80% umur>=120 momentum 1.5x | TP2 SL0.7 600s
  A n=212 rata 0,902x tanpa terbaik 0,897x. B n=81 rata 0,872x tanpa terbaik 0,864x menang 38,3%. p B None.
- F8 (tidak ada n_A cukup): (b) + P1 jeda 3-8
  A n=0 rata — tanpa terbaik —. B n=0 rata — tanpa terbaik — menang —. p B None.
- Transfer: gerbang dengan jual F1: parsial 50% 3x sisa TP5 SL0.7 600s. B n=31 rata 1,218x tanpa terbaik 1,135x. p 0.06607.

## Irisan segar dan C

Gerbang pada segar: n=0 rata — tanpa terbaik —.
Gerbang pada C tercemar: n=38 rata 1,000x tanpa terbaik 0,902x.

Konfigurasi yang lolos A+B tetapi bukan pilihan A: 6. Mereka tidak menjadi pemenang.
- F1 parsial 50% 2x sisa TP5 SL0.7 600s: A 1,070x (n=234), B 1,097x (n=51).
- F1 parsial 50% 2x sisa TP3 SL0.7 600s: A 1,018x (n=234), B 1,057x (n=51).
- F1 parsial 50% 2x sisa TP3 SL0.7 1800s: A 1,021x (n=234), B 1,061x (n=51).
- F1 parsial 50% 2x sisa TP5 SL0.7 1800s: A 1,069x (n=234), B 1,101x (n=51).
- F1 parsial 50% 3x sisa TP5 SL0.7 1800s: A 1,087x (n=234), B 1,135x (n=51).
- F1 moonbag 70% di 3x sisa trail 30% 1800s: A 1,022x (n=234), B 1,065x (n=51).

## Batas

- Setel di A, uji di B. C tidak memilih. Segar tidak memilih.
- Jam 12–16 pada aturan (b) tidak dicari ulang.
- Anti-honeypot, mint, freeze, Token-2022, Jupiter, narasi: tidak ada di rekaman.
- Tape wallet putus di 5 menit dan 150 baris. Aturan ukuran trade gagal tertutup kalau cakupan lebih pendek.
- Akhir pekan hanya punya sekitar dua minggu kalender.
- Umur 30 menit dan 1–3 hari tidak dicoba: rekaman sebelumnya kosong di 30 menit.
- Waktu 197 dtk.

Paper saja.
