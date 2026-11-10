TIDAK LAYAK DIPAKAI. 5 modul lolos B dan jumlah lulus di atas null, tetapi tidak ada yang p-nya di bawah Bonferroni 7.34e-10. C tercemar.

# Amplifikasi tepi aturan (b) sebagai modul Bom, 10 Nov 2026, PAPER

Cuma ada satu arsitektur: tim agen Bom. Strategi lain di bawah ini calon tugas agen, bukan bot kedua.
Narasi X tidak ada di data perekam, jadi aturan Bom di backtest tidak punya cek narasi.

## Perbandingan portofolio

A dan B dipakai untuk menilai. C sudah pernah dilihat (tercemar). Segar = koin lahir sesudah 10 Nov 07:17 UTC, kalau ada.
Angka $ adalah saldo akhir dari $200, plus penurunan maksimum (DD) di jalur itu.
Suara: lima agen, masuk kalau minimal 4 ACC. Agen yang terlambat tidak langsung SKIP: ditunggu 1, 2, atau 3 detik di atas cek pertama (detik ke-2), terutama untuk narasi.
Setelah suara cukup, harga dicek lagi. Masuk hanya kalau harga masih dalam ±10%, ±15%, ±25%, atau tanpa batas, dari harga cek pertama. Kalau sudah pump atau dump melewati pita, SKIP. Lalu jeda eksekusi 1 detik. Jual tetap jaga Bom.
Narasi tidak bisa diuji. Narasi-SKIP berarti butuh 4/4 proksi. Narasi-ACC berarti butuh minimal 3/4. Baris 5/5 sama dengan 4/4 karena narasi hanya bisa diasumsikan ACC, tidak diukur. Kalau narasi tidak menjawab sama sekali, 5/5 tidak pernah terjadi.
Proksi sampai waktu tunggu selesai: rug = dev belum jual, pembeli unik selain dev ≥3, beli terbesar ≤50%. Latar = beli dev 0–2 SOL dan belum jual. Data = harga ≥1,5x dari detik 0,4 dan rasio beli ≥65%. Whale = ada wallet pintar yang sudah beli.

| Portofolio | Irisan | n | Rata | Menang (Wilson) | Tanpa terbaik | $200 8% maks1 / DD | 8% maks5 / DD | 10% maks1 / DD | 10% maks5 / DD |
|---|---|---:|---:|---|---:|---|---|---|---|
| (1) Bom saja | | | | | | | | | |
| | A | 239 | 0,912x | 25,9% [20,8%–31,8%] | 0,904x | $39 / DD 82,5% | $26 / DD 87,4% | $24 / DD 89,4% | $14 / DD 93,2% |
| | B | 114 | 0,827x | 21,1% [14,6%–29,4%] | 0,809x | $46 / DD 78,6% | $36 / DD 83,3% | $31 / DD 85,9% | $23 / DD 89,7% |
| | C | 185 | 0,792x | 20,5% [15,3%–26,9%] | 0,781x | $21 / DD 89,7% | $7 / DD 96,5% | $11 / DD 94,5% | $3 / DD 98,6% |
| | segar | 0 | — | — | — | — | — | — | — |
| (2) mom120 (a) saja, modul data | | | | | | | | | |
| | A | 182 | 1,011x | 41,8% [34,8%–49,0%] | 0,998x | $171 / DD 52,0% | $188 / DD 50,4% | $157 / DD 61,2% | $173 / DD 59,7% |
| | B | 67 | 1,069x | 28,4% [19,0%–40,1%] | 0,969x | $245 / DD 29,1% | $240 / DD 28,5% | $246 / DD 35,1% | $239 / DD 34,7% |
| | C | 140 | 1,116x | 38,6% [30,9%–46,8%] | 1,061x | $667 / DD 29,1% | $479 / DD 31,5% | $815 / DD 35,2% | $533 / DD 38,4% |
| | segar | 0 | — | — | — | — | — | — | — |
| (3) aturan (b) saja, modul data | | | | | | | | | |
| | A | 234 | 1,070x | 50,9% [44,5%–57,2%] | 1,060x | $359 / DD 41,9% | $507 / DD 33,2% | $380 / DD 51,0% | $574 / DD 39,9% |
| | B | 51 | 1,097x | 49,0% [35,9%–62,3%] | 1,054x | $274 / DD 35,6% | $270 / DD 37,5% | $289 / DD 42,6% | $283 / DD 44,6% |
| | C | 130 | 1,014x | 42,3% [34,2%–50,9%] | 0,996x | $127 / DD 54,2% | $183 / DD 50,5% | $106 / DD 63,9% | $167 / DD 58,8% |
| | segar | 0 | — | — | — | — | — | — | — |
| (4) Bom ATAU mom120 | | | | | | | | | |
| | A | 372 | 0,941x | 33,1% [28,5%–38,0%] | 0,935x | $33 / DD 87,2% | $21 / DD 90,8% | $19 / DD 92,8% | $10 / DD 95,6% |
| | B | 167 | 0,922x | 24,6% [18,6%–31,6%] | 0,881x | $60 / DD 72,9% | $52 / DD 79,0% | $42 / DD 81,7% | $34 / DD 86,7% |
| | C | 297 | 0,934x | 28,3% [23,5%–33,7%] | 0,907x | $87 / DD 77,9% | $22 / DD 90,4% | $61 / DD 85,5% | $11 / DD 95,4% |
| | segar | 0 | — | — | — | — | — | — | — |
| (5) Bom DAN mom120, waktu lebih akhir | | | | | | | | | |
| | A | 49 | 1,057x | 30,6% [19,5%–44,5%] | 1,021x | $207 / DD 17,8% | $236 / DD 17,8% | $206 / DD 22,2% | $243 / DD 22,2% |
| | B | 14 | 0,850x | 14,3% [4,0%–39,9%] | 0,701x | $166 / DD 26,7% | $166 / DD 26,7% | $157 / DD 32,4% | $157 / DD 32,4% |
| | C | 28 | 0,909x | 28,6% [15,3%–47,1%] | 0,839x | $166 / DD 22,6% | $157 / DD 26,8% | $156 / DD 27,8% | $146 / DD 32,7% |
| | segar | 0 | — | — | — | — | — | — | — |
| (6) OR modul keluarga | | | | | | | | | |
| | A | 881 | 0,965x | 24,3% [21,6%–27,2%] | 0,960x | $19 / DD 93,2% | $13 / DD 95,7% | $10 / DD 96,7% | $6 / DD 98,2% |
| | B | 184 | 0,933x | 16,8% [12,1%–22,9%] | 0,904x | $76 / DD 69,0% | $66 / DD 72,7% | $58 / DD 77,1% | $49 / DD 80,5% |
| | C | 224 | 0,942x | 25,0% [19,8%–31,1%] | 0,935x | $71 / DD 69,8% | $66 / DD 72,2% | $54 / DD 77,9% | $49 / DD 80,1% |
| | segar | 0 | — | — | — | — | — | — | — |
| (7) finalis amplifikasi terbaik | | | | | | | | | |
| | A | 103 | 1,317x | 56,3% [46,7%–65,5%] | 1,284x | $1161 / DD 18,9% | $1813 / DD 16,6% | $1658 / DD 23,1% | $2827 / DD 20,6% |
| | B | 31 | 1,229x | 58,1% [40,8%–73,6%] | 1,115x | $329 / DD 13,8% | $324 / DD 16,3% | $365 / DD 17,1% | $357 / DD 20,1% |
| | C | 38 | 1,000x | 26,3% [15,0%–42,0%] | 0,902x | $175 / DD 44,1% | $175 / DD 44,1% | $163 / DD 52,0% | $163 / DD 52,0% |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 1s, pita 10% | | | | | | | | | |
| | A | 2 | 0,370x | 0,0% [0,0%–65,8%] | 0,326x | $180 / DD 9,8% | $180 / DD 9,8% | $176 / DD 12,2% | $176 / DD 12,2% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 1s, pita 10% | | | | | | | | | |
| | A | 397 | 0,654x | 10,1% [7,5%–13,4%] | 0,646x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 219 | 0,494x | 3,7% [1,9%–7,0%] | 0,479x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | C | 235 | 0,590x | 9,8% [6,6%–14,3%] | 0,580x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 1s, pita 10% | | | | | | | | | |
| | A | 2 | 0,370x | 0,0% [0,0%–65,8%] | 0,326x | $180 / DD 9,8% | $180 / DD 9,8% | $176 / DD 12,2% | $176 / DD 12,2% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 1s, pita 15% | | | | | | | | | |
| | A | 2 | 0,370x | 0,0% [0,0%–65,8%] | 0,326x | $180 / DD 9,8% | $180 / DD 9,8% | $176 / DD 12,2% | $176 / DD 12,2% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 1s, pita 15% | | | | | | | | | |
| | A | 442 | 0,673x | 10,9% [8,3%–14,1%] | 0,664x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 246 | 0,485x | 3,3% [1,7%–6,3%] | 0,472x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | C | 267 | 0,609x | 10,5% [7,4%–14,7%] | 0,599x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 1s, pita 15% | | | | | | | | | |
| | A | 2 | 0,370x | 0,0% [0,0%–65,8%] | 0,326x | $180 / DD 9,8% | $180 / DD 9,8% | $176 / DD 12,2% | $176 / DD 12,2% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 1s, pita 25% | | | | | | | | | |
| | A | 3 | 0,355x | 0,0% [0,0%–56,2%] | 0,326x | $171 / DD 14,7% | $171 / DD 14,7% | $164 / DD 18,1% | $164 / DD 18,1% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 1s, pita 25% | | | | | | | | | |
| | A | 491 | 0,667x | 11,2% [8,7%–14,3%] | 0,659x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 269 | 0,506x | 4,5% [2,6%–7,6%] | 0,494x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | C | 326 | 0,632x | 11,7% [8,6%–15,6%] | 0,624x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 1s, pita 25% | | | | | | | | | |
| | A | 3 | 0,355x | 0,0% [0,0%–56,2%] | 0,326x | $171 / DD 14,7% | $171 / DD 14,7% | $164 / DD 18,1% | $164 / DD 18,1% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 1s, pita tanpa batas | | | | | | | | | |
| | A | 5 | 0,837x | 20,0% [3,6%–62,4%] | 0,348x | $185 / DD 19,3% | $185 / DD 19,3% | $180 / DD 23,6% | $180 / DD 23,6% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 1s, pita tanpa batas | | | | | | | | | |
| | A | 654 | 0,666x | 11,9% [9,7%–14,6%] | 0,660x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 345 | 0,541x | 6,1% [4,0%–9,1%] | 0,531x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | C | 423 | 0,630x | 11,6% [8,9%–15,0%] | 0,625x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 1s, pita tanpa batas | | | | | | | | | |
| | A | 5 | 0,837x | 20,0% [3,6%–62,4%] | 0,348x | $185 / DD 19,3% | $185 / DD 19,3% | $180 / DD 23,6% | $180 / DD 23,6% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 2s, pita 10% | | | | | | | | | |
| | A | 2 | 0,560x | 0,0% [0,0%–65,8%] | 0,326x | $186 / DD 7,0% | $186 / DD 7,0% | $183 / DD 8,7% | $183 / DD 8,7% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 2s, pita 10% | | | | | | | | | |
| | A | 356 | 0,771x | 13,2% [10,1%–17,1%] | 0,762x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 194 | 0,753x | 12,9% [8,9%–18,3%] | 0,727x | $13 / DD 94,5% | $3 / DD 98,7% | $6 / DD 97,5% | $1 / DD 99,5% |
| | C | 204 | 0,748x | 13,7% [9,7%–19,1%] | 0,730x | $4 / DD 98,0% | $2 / DD 98,9% | $1 / DD 99,3% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 2s, pita 10% | | | | | | | | | |
| | A | 2 | 0,560x | 0,0% [0,0%–65,8%] | 0,326x | $186 / DD 7,0% | $186 / DD 7,0% | $183 / DD 8,7% | $183 / DD 8,7% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 2s, pita 15% | | | | | | | | | |
| | A | 3 | 0,482x | 0,0% [0,0%–56,2%] | 0,326x | $176 / DD 12,0% | $176 / DD 12,0% | $170 / DD 14,8% | $170 / DD 14,8% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 2s, pita 15% | | | | | | | | | |
| | A | 411 | 0,777x | 13,9% [10,9%–17,5%] | 0,769x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 225 | 0,755x | 13,8% [9,9%–18,9%] | 0,732x | $9 / DD 95,8% | $2 / DD 99,3% | $4 / DD 98,2% | $1 / DD 99,5% |
| | C | 228 | 0,750x | 14,5% [10,5%–19,6%] | 0,734x | $3 / DD 98,3% | $1 / DD 99,3% | $1 / DD 99,4% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 2s, pita 15% | | | | | | | | | |
| | A | 3 | 0,482x | 0,0% [0,0%–56,2%] | 0,326x | $176 / DD 12,0% | $176 / DD 12,0% | $170 / DD 14,8% | $170 / DD 14,8% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 2s, pita 25% | | | | | | | | | |
| | A | 4 | 0,443x | 0,0% [0,0%–49,0%] | 0,326x | $167 / DD 16,7% | $167 / DD 16,7% | $159 / DD 20,6% | $159 / DD 20,6% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 2s, pita 25% | | | | | | | | | |
| | A | 497 | 0,796x | 14,7% [11,8%–18,1%] | 0,789x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 256 | 0,761x | 14,1% [10,3%–18,9%] | 0,741x | $6 / DD 97,1% | $1 / DD 99,5% | $2 / DD 98,9% | $1 / DD 99,5% |
| | C | 289 | 0,761x | 15,6% [11,8%–20,2%] | 0,748x | $2 / DD 99,1% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 2s, pita 25% | | | | | | | | | |
| | A | 4 | 0,443x | 0,0% [0,0%–49,0%] | 0,326x | $167 / DD 16,7% | $167 / DD 16,7% | $159 / DD 20,6% | $159 / DD 20,6% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 2s, pita tanpa batas | | | | | | | | | |
| | A | 5 | 0,912x | 20,0% [3,6%–62,4%] | 0,443x | $190 / DD 16,7% | $190 / DD 16,7% | $187 / DD 20,6% | $187 / DD 20,6% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 2s, pita tanpa batas | | | | | | | | | |
| | A | 774 | 0,785x | 15,6% [13,2%–18,4%] | 0,780x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 389 | 0,789x | 16,5% [13,1%–20,5%] | 0,776x | $4 / DD 98,3% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | C | 504 | 0,712x | 13,9% [11,1%–17,2%] | 0,705x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 2s, pita tanpa batas | | | | | | | | | |
| | A | 5 | 0,912x | 20,0% [3,6%–62,4%] | 0,443x | $190 / DD 16,7% | $190 / DD 16,7% | $187 / DD 20,6% | $187 / DD 20,6% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 3s, pita 10% | | | | | | | | | |
| | A | 1 | 0,325x | 0,0% [0,0%–79,3%] | — | $189 / DD 5,4% | $189 / DD 5,4% | $187 / DD 6,7% | $187 / DD 6,7% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 3s, pita 10% | | | | | | | | | |
| | A | 194 | 0,850x | 13,9% [9,7%–19,5%] | 0,835x | $19 / DD 91,2% | $16 / DD 92,8% | $10 / DD 95,4% | $8 / DD 96,4% |
| | B | 37 | 0,824x | 13,5% [5,9%–28,0%] | 0,770x | $118 / DD 45,4% | $113 / DD 47,0% | $102 / DD 53,7% | $96 / DD 55,4% |
| | C | 54 | 0,715x | 13,0% [6,4%–24,4%] | 0,676x | $60 / DD 70,0% | $54 / DD 72,8% | $43 / DD 78,3% | $38 / DD 80,8% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 3s, pita 10% | | | | | | | | | |
| | A | 1 | 0,325x | 0,0% [0,0%–79,3%] | — | $189 / DD 5,4% | $189 / DD 5,4% | $187 / DD 6,7% | $187 / DD 6,7% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 3s, pita 15% | | | | | | | | | |
| | A | 1 | 0,325x | 0,0% [0,0%–79,3%] | — | $189 / DD 5,4% | $189 / DD 5,4% | $187 / DD 6,7% | $187 / DD 6,7% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 3s, pita 15% | | | | | | | | | |
| | A | 229 | 0,851x | 15,3% [11,2%–20,5%] | 0,838x | $15 / DD 93,9% | $10 / DD 95,5% | $7 / DD 97,1% | $4 / DD 98,1% |
| | B | 51 | 0,863x | 17,6% [9,6%–30,3%] | 0,825x | $109 / DD 52,7% | $104 / DD 54,0% | $91 / DD 61,6% | $86 / DD 63,0% |
| | C | 68 | 0,697x | 11,8% [6,1%–21,5%] | 0,666x | $39 / DD 80,7% | $35 / DD 82,5% | $25 / DD 87,6% | $22 / DD 89,0% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 3s, pita 15% | | | | | | | | | |
| | A | 1 | 0,325x | 0,0% [0,0%–79,3%] | — | $189 / DD 5,4% | $189 / DD 5,4% | $187 / DD 6,7% | $187 / DD 6,7% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 3s, pita 25% | | | | | | | | | |
| | A | 3 | 0,326x | 0,0% [0,0%–56,2%] | 0,325x | $169 / DD 15,3% | $169 / DD 15,3% | $162 / DD 18,9% | $162 / DD 18,9% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 3s, pita 25% | | | | | | | | | |
| | A | 289 | 0,836x | 15,2% [11,5%–19,8%] | 0,823x | $5 / DD 98,1% | $3 / DD 98,9% | $2 / DD 99,4% | $1 / DD 99,5% |
| | B | 67 | 0,855x | 17,9% [10,6%–28,7%] | 0,815x | $92 / DD 60,9% | $80 / DD 63,9% | $73 / DD 69,6% | $61 / DD 72,9% |
| | C | 107 | 0,777x | 15,9% [10,2%–24,0%] | 0,756x | $28 / DD 86,0% | $24 / DD 87,8% | $16 / DD 91,9% | $14 / DD 93,2% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 3s, pita 25% | | | | | | | | | |
| | A | 3 | 0,326x | 0,0% [0,0%–56,2%] | 0,325x | $169 / DD 15,3% | $169 / DD 15,3% | $162 / DD 18,9% | $162 / DD 18,9% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 0 | — | — | — | — | — | — | — |
| | segar | 0 | — | — | — | — | — | — | — |
| (8) suara 4/4 narasi-SKIP, tunggu 3s, pita tanpa batas | | | | | | | | | |
| | A | 4 | 0,942x | 25,0% [4,6%–69,9%] | 0,326x | $194 / DD 15,3% | $194 / DD 15,3% | $191 / DD 18,9% | $191 / DD 18,9% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 1 | 0,398x | 0,0% [0,0%–79,3%] | — | $190 / DD 4,8% | $190 / DD 4,8% | $188 / DD 6,0% | $188 / DD 6,0% |
| | segar | 0 | — | — | — | — | — | — | — |
| (9) suara ≥3/4 narasi-ACC, tunggu 3s, pita tanpa batas | | | | | | | | | |
| | A | 582 | 0,798x | 17,4% [14,5%–20,6%] | 0,791x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | B | 171 | 0,921x | 24,6% [18,7%–31,5%] | 0,906x | $95 / DD 77,0% | $44 / DD 89,9% | $72 / DD 85,0% | $27 / DD 94,7% |
| | C | 307 | 0,710x | 16,0% [12,3%–20,5%] | 0,702x | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% | $1 / DD 99,5% |
| | segar | 0 | — | — | — | — | — | — | — |
| (10) suara 5/5 narasi-ACC, tunggu 3s, pita tanpa batas | | | | | | | | | |
| | A | 4 | 0,942x | 25,0% [4,6%–69,9%] | 0,326x | $194 / DD 15,3% | $194 / DD 15,3% | $191 / DD 18,9% | $191 / DD 18,9% |
| | B | 0 | — | — | — | — | — | — | — |
| | C | 1 | 0,398x | 0,0% [0,0%–79,3%] | — | $190 / DD 4,8% | $190 / DD 4,8% | $188 / DD 6,0% | $188 / DD 6,0% |
| | segar | 0 | — | — | — | — | — | — | — |

### Bom saja lawan Bom + modul

| Modul | Agen | Irisan | n | Rata | Menang (Wilson) | Tanpa terbaik | $200 8% maks1 / DD | 8% maks5 / DD | 10% maks1 / DD | 10% maks5 / DD |
|---|---|---|---:|---:|---|---:|---|---|---|---|
| Bom saja | | | | | | | | | |
| | A | 239 | 0,912x | 25,9% [20,8%–31,8%] | 0,904x | $39 / DD 82,5% | $26 / DD 87,4% | $24 / DD 89,4% | $14 / DD 93,2% |
| | B | 114 | 0,827x | 21,1% [14,6%–29,4%] | 0,809x | $46 / DD 78,6% | $36 / DD 83,3% | $31 / DD 85,9% | $23 / DD 89,7% |
| | C | 185 | 0,792x | 20,5% [15,3%–26,9%] | 0,781x | $21 / DD 89,7% | $7 / DD 96,5% | $11 / DD 94,5% | $3 / DD 98,6% |
| | segar | 0 | — | — | — | — | — | — | — |
| Bom+data: growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer bebas mcap bebas liq be | TP5 SL0.7 1800s | data: filter jam lahir UTC (gerbang) | | | | | | | | | |
|  | | | | | | | | | |
| | A | 3 | 0,867x | 66,7% [20,8%–93,9%] | 0,683x | $193 / DD 5,4% | $193 / DD 5,4% | $192 / DD 6,7% | $192 / DD 6,7% |
| | B | 1 | 0,676x | 0,0% [0,0%–79,3%] | — | $195 / DD 2,6% | $195 / DD 2,6% | $194 / DD 3,2% | $194 / DD 3,2% |
| | C | 2 | 0,326x | 0,0% [0,0%–65,8%] | 0,326x | $179 / DD 10,5% | $179 / DD 10,5% | $174 / DD 13,0% | $174 / DD 13,0% |
| | segar | 0 | — | — | — | — | — | — | — |
| Bom+data: growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer bebas mcap bebas liq be | TP5 SL0.7 1800s | data: filter jam lahir UTC (gerbang) | | | | | | | | | |
|  | | | | | | | | | |
| | A | 3 | 0,867x | 66,7% [20,8%–93,9%] | 0,683x | $193 / DD 5,4% | $193 / DD 5,4% | $192 / DD 6,7% | $192 / DD 6,7% |
| | B | 1 | 0,676x | 0,0% [0,0%–79,3%] | — | $195 / DD 2,6% | $195 / DD 2,6% | $194 / DD 3,2% | $194 / DD 3,2% |
| | C | 2 | 0,326x | 0,0% [0,0%–65,8%] | 0,326x | $179 / DD 10,5% | $179 / DD 10,5% | $174 / DD 13,0% | $174 / DD 13,0% |
| | segar | 0 | — | — | — | — | — | — | — |
| Bom+data: growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer bebas mcap bebas liq>=8 | TP5 SL0.7 1800s | data: filter jam lahir UTC (gerbang) | | | | | | | | | |
|  | | | | | | | | | |
| | A | 3 | 0,867x | 66,7% [20,8%–93,9%] | 0,683x | $193 / DD 5,4% | $193 / DD 5,4% | $192 / DD 6,7% | $192 / DD 6,7% |
| | B | 1 | 0,676x | 0,0% [0,0%–79,3%] | — | $195 / DD 2,6% | $195 / DD 2,6% | $194 / DD 3,2% | $194 / DD 3,2% |
| | C | 2 | 0,326x | 0,0% [0,0%–65,8%] | 0,326x | $179 / DD 10,5% | $179 / DD 10,5% | $174 / DD 13,0% | $174 / DD 13,0% |
| | segar | 0 | — | — | — | — | — | — | — |
| Bom+data: growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer bebas mcap bebas liq>=8 | TP5 SL0.7 1800s | data: filter jam lahir UTC (gerbang) | | | | | | | | | |
|  | | | | | | | | | |
| | A | 3 | 0,867x | 66,7% [20,8%–93,9%] | 0,683x | $193 / DD 5,4% | $193 / DD 5,4% | $192 / DD 6,7% | $192 / DD 6,7% |
| | B | 1 | 0,676x | 0,0% [0,0%–79,3%] | — | $195 / DD 2,6% | $195 / DD 2,6% | $194 / DD 3,2% | $194 / DD 3,2% |
| | C | 2 | 0,326x | 0,0% [0,0%–65,8%] | 0,326x | $179 / DD 10,5% | $179 / DD 10,5% | $174 / DD 13,0% | $174 / DD 13,0% |
| | segar | 0 | — | — | — | — | — | — | — |
| Bom+data: growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer>=20 mcap bebas liq beba | TP5 SL0.7 1800s | data: filter jam lahir UTC (gerbang) | | | | | | | | | |
|  | | | | | | | | | |
| | A | 3 | 0,867x | 66,7% [20,8%–93,9%] | 0,683x | $193 / DD 5,4% | $193 / DD 5,4% | $192 / DD 6,7% | $192 / DD 6,7% |
| | B | 1 | 0,676x | 0,0% [0,0%–79,3%] | — | $195 / DD 2,6% | $195 / DD 2,6% | $194 / DD 3,2% | $194 / DD 3,2% |
| | C | 2 | 0,326x | 0,0% [0,0%–65,8%] | 0,326x | $179 / DD 10,5% | $179 / DD 10,5% | $174 / DD 13,0% | $174 / DD 13,0% |
| | segar | 0 | — | — | — | — | — | — | — |

Gerbang (data, whale, rug, latar): koin harus lolos Bom dan modul, masuk di waktu yang lebih lambat, jual tetap jaga Bom (TP3 SL0,5 600 dtk).
Jalur cepat: Bom ATAU modul, masuk di sinyal pertama, masing-masing pakai cara jualnya sendiri.
Jaga: masuk tetap sinyal Bom, cara jual diganti milik modul.

## Modul kandidat untuk Bom v2

### 1. Agen data
- Tugas: filter jam lahir UTC.
- Sinyal: snap umur 120 jeda 0.4 dip 0.0.
- Filter: growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer bebas mcap bebas liq bebas jam 12-16 dd<=0.35 top10 bebas.
- Jual: TP5 SL0.7 1800s.
- A n=103 rata 1,317x; B n=31 rata 1,229x tanpa terbaik 1,115x.
- p bootstrap B (batas atas) 0.076. Ambang Bonferroni 7.343e-10.
- Hasil Bom+modul ada di tabel atas. C tercemar.
- Data segar: belum ada koin sesudah 10 Nov 07:17 UTC.

### 2. Agen data
- Tugas: filter jam lahir UTC.
- Sinyal: snap umur 120 jeda 0.4 dip 0.0.
- Filter: growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer bebas mcap bebas liq bebas jam 12-16 dd bebas top10 bebas.
- Jual: TP5 SL0.7 1800s.
- A n=103 rata 1,317x; B n=31 rata 1,229x tanpa terbaik 1,115x.
- p bootstrap B (batas atas) 0.076. Ambang Bonferroni 7.343e-10.
- Hasil Bom+modul ada di tabel atas. C tercemar.
- Data segar: belum ada koin sesudah 10 Nov 07:17 UTC.

### 3. Agen data
- Tugas: filter jam lahir UTC.
- Sinyal: snap umur 120 jeda 0.4 dip 0.0.
- Filter: growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer bebas mcap bebas liq>=8 jam 12-16 dd<=0.35 top10 bebas.
- Jual: TP5 SL0.7 1800s.
- A n=103 rata 1,317x; B n=31 rata 1,229x tanpa terbaik 1,115x.
- p bootstrap B (batas atas) 0.076. Ambang Bonferroni 7.343e-10.
- Hasil Bom+modul ada di tabel atas. C tercemar.
- Data segar: belum ada koin sesudah 10 Nov 07:17 UTC.

### 4. Agen data
- Tugas: filter jam lahir UTC.
- Sinyal: snap umur 120 jeda 0.4 dip 0.0.
- Filter: growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer bebas mcap bebas liq>=8 jam 12-16 dd bebas top10 bebas.
- Jual: TP5 SL0.7 1800s.
- A n=103 rata 1,317x; B n=31 rata 1,229x tanpa terbaik 1,115x.
- p bootstrap B (batas atas) 0.076. Ambang Bonferroni 7.343e-10.
- Hasil Bom+modul ada di tabel atas. C tercemar.
- Data segar: belum ada koin sesudah 10 Nov 07:17 UTC.

### 5. Agen data
- Tugas: filter jam lahir UTC.
- Sinyal: snap umur 120 jeda 0.4 dip 0.0.
- Filter: growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer>=20 mcap bebas liq bebas jam 12-16 dd<=0.35 top10 bebas.
- Jual: TP5 SL0.7 1800s.
- A n=103 rata 1,317x; B n=31 rata 1,229x tanpa terbaik 1,115x.
- p bootstrap B (batas atas) 0.076. Ambang Bonferroni 7.343e-10.
- Hasil Bom+modul ada di tabel atas. C tercemar.
- Data segar: belum ada koin sesudah 10 Nov 07:17 UTC.

## Pencarian
- Kombinasi 68093568. Lulus A+B 108251.
- Null 20x: 10, 0, 0, 0, 0, 14, 0, 0, 0, 0, 0, 18, 0, 0, 3, 0, 14, 0, 0, 0.
- Cache: `memescan-data-42685043176`; koin dimuat 135797; segar 0.
- Ukuran posisi di tabel adalah 8% dan 10% saldo, majemuk, maks 1 dan 5. Kelly dihitung dari trade A saja, lalu dicek di B, tidak dipakai memilih modul.

Kelly finalis pertama (dari rata log di A) dilaporkan di JSON. DD ada di kolom saldo.

## Yang ditolak di A (gagal B atau bukan 5 teratas)

- reentry D120 jeda 3-8 growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer bebas mcap bebas liq bebas jam 16-20 dd<=0.15 top10 bebas | TP10 SL0.7 120s A 1,734x (n=36) B 1,670x (n=1)
- reentry D120 jeda 3-8 growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer bebas mcap bebas liq>=8 jam 16-20 dd<=0.15 top10 bebas | TP10 SL0.7 120s A 1,734x (n=36) B 1,670x (n=1)
- reentry D120 jeda 3-8 growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer>=20 mcap bebas liq bebas jam 16-20 dd<=0.15 top10 bebas | TP10 SL0.7 120s A 1,734x (n=36) B 1,670x (n=1)
- reentry D120 jeda 3-8 growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer>=20 mcap bebas liq>=8 jam 16-20 dd<=0.15 top10 bebas | TP10 SL0.7 120s A 1,734x (n=36) B 1,670x (n=1)
- reentry D120 jeda 3-8 growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer>=50 mcap bebas liq bebas jam 16-20 dd<=0.15 top10 bebas | TP10 SL0.7 120s A 1,734x (n=36) B 1,670x (n=1)
- reentry D120 jeda 3-8 growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder bebas buyer>=50 mcap bebas liq>=8 jam 16-20 dd<=0.15 top10 bebas | TP10 SL0.7 120s A 1,734x (n=36) B 1,670x (n=1)
- reentry D120 jeda 3-8 growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder>=15 buyer bebas mcap bebas liq bebas jam 16-20 dd<=0.15 top10 bebas | TP10 SL0.7 120s A 1,734x (n=36) B 1,670x (n=1)
- reentry D120 jeda 3-8 growth>=3 beli>=0.65 vol>=3 laju>=1.5 holder>=15 buyer bebas mcap bebas liq>=8 jam 16-20 dd<=0.15 top10 bebas | TP10 SL0.7 120s A 1,734x (n=36) B 1,670x (n=1)

Paper saja. Jangan dipakai live.
