BELUM LAYAK DIPAKAI. Di holdout, aturan b masih rata di atas 1 di C setelah buang koin terbaik, tetapi ini satu uji terkunci, bukan izin live. TIDAK LAYAK. 2160504 kombinasi, lulus ekonomi 1461, null rata-rata 0,00 (maks 0,0). Finalis protokol A→B→C yang lolos syarat: 0. Tidak ada yang lolos koreksi uji berganda atas seluruh pencarian.

# Riset grid penuh (semua koin standar) + holdout di luar sampel, 10 Nov 2026, PAPER

Bukan saran beli. Tidak ada kunci, tidak ada transaksi.

## Data
- Kunci cache: `memescan-data-42685043176`
- Berkas: 15 file rec, 351456 baris, 286987 punya trade wallet.
- Periode rekaman (t0 pertama–terakhir): 27 Oct 2026 00:00 UTC / 07:00 WIB – 10 Nov 2026 07:17 UTC / 14:17 WIB.
- Koin kurva standar: 135797. Yang diuji (sampel merata waktu, kalau dipotong): 135797.
- Periode yang diuji: 27 Oct 2026 00:00 UTC / 07:00 WIB – 10 Nov 2026 07:17 UTC / 14:17 WIB.
- Potongan A/B/C: 02 Nov 2026 17:43 UTC / 00:43 WIB / 05 Nov 2026 16:55 UTC / 23:55 WIB.
- Jumlah koin A/B/C: 67898/27159/40740.
- Dedupe: 8353665 baris trade dibuang di 281776 koin (kunci wallet+sisi+SOL, selisih umur ≤0,3 dtk). Signature tidak ada di rekaman.
- Hash skrip sha256: `b2b66f156da5f2b7a7f044360b290a86ae2e5e2b54185ccadcd609db949f3fe2`

## Protokol
- Pilih hanya di A (n_A≥30, rata tertinggi). Lima teratas, satu per pola trade (cara jual yang hasilnya sama di A dihitung satu).
- B harus rata >1. C diuji sekali, hanya untuk yang lolos B.
- Lulus ekonomi: n_C≥30, rata A, B, dan C >1, dan C tanpa koin terbaik >1.
- Null mengacak fitur 20 kali. Jumlah lulus harus mengalahkan null.
- Bonferroni pencarian penuh: 0,05/2160504 = 2.3142748173574316e-08.
- Bonferroni hanya pada yang benar-benar diuji di C (k=0): None.
- Top 10 di bawah ini melihat C. Itu deskripsi, bukan seleksi, dan tidak dihitung lulus.

## Kombinasi dan lulus per keluarga

| Keluarga | Kombinasi | Lulus ekonomi | Null rata | Null maks |
|---|---:|---:|---:|---:|
| Copy | 7290 | 0 | 0,00 | 0,0 |
| Bom | 1741824 | 14 | 0,00 | 0,0 |
| Momentum | 408240 | 1447 | 0,00 | 0,0 |
| Sniper | 630 | 0 | 0,00 | 0,0 |
| Graduation | 2520 | 0 | 0,00 | 0,0 |

Total kombinasi 2160504. Total lulus ekonomi 1461.
Null global (20): 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.
Null rata 0,00, maks 0,0.

## Lima teratas menurut A (seleksi resmi)

### 1. Momentum D30 jeda 0.4 — growth>=3 beli bebas dd<=15% vol bebas laju>=1.5 top10<=35% — TP3 SL0.5 120s
- A: n=46 rata 1,251x menang 58,7% Wilson [44,3–71,7%] tanpa terbaik 1,214x terbaik 2,877x
- B: n=19 rata 0,904x menang 42,1% Wilson [23,1–63,7%] tanpa terbaik 0,819x terbaik 2,441x
- C: tidak diuji (gagal di B, atau B tidak di atas 1).

### 2. Momentum D30 jeda 1 — growth>=3 beli bebas dd<=15% vol bebas laju>=1.5 top10<=35% — TP3 SL0.5 120s
- A: n=46 rata 1,249x menang 58,7% Wilson [44,3–71,7%] tanpa terbaik 1,213x terbaik 2,877x
- B: n=19 rata 0,904x menang 42,1% Wilson [23,1–63,7%] tanpa terbaik 0,819x terbaik 2,441x
- C: tidak diuji (gagal di B, atau B tidak di atas 1).

### 3. Momentum D30 jeda 0.4 — growth>=3 beli bebas dd<=15% vol>=3 laju>=1.5 top10<=35% — TP3 SL0.5 120s
- A: n=37 rata 1,237x menang 59,5% Wilson [43,5–73,7%] tanpa terbaik 1,191x terbaik 2,877x
- B: n=17 rata 0,760x menang 35,3% Wilson [17,3–58,7%] tanpa terbaik 0,689x terbaik 1,900x
- C: tidak diuji (gagal di B, atau B tidak di atas 1).

### 4. Momentum D30 jeda 1 — growth>=3 beli bebas dd<=15% vol>=3 laju>=1.5 top10<=35% — TP3 SL0.5 120s
- A: n=37 rata 1,237x menang 59,5% Wilson [43,5–73,7%] tanpa terbaik 1,191x terbaik 2,877x
- B: n=17 rata 0,760x menang 35,3% Wilson [17,3–58,7%] tanpa terbaik 0,689x terbaik 1,900x
- C: tidak diuji (gagal di B, atau B tidak di atas 1).

### 5. Bom D60 jeda 0.4 — dev jual bebas top10 bebas buyer bebas mcap bebas liq>=8 smart bebas devbuy 0.5-2 holder bebas rug pembuat 0 — tahan sampai habis
- A: n=34 rata 1,232x menang 26,5% Wilson [14,6–43,1%] tanpa terbaik 1,075x terbaik 6,397x
- B: n=13 rata 0,633x menang 15,4% Wilson [4,3–42,2%] tanpa terbaik 0,599x terbaik 1,037x
- C: tidak diuji (gagal di B, atau B tidak di atas 1).

## Terbaik di A per keluarga (C tidak dibuka di sini)

- Copy: Copy-wallet jeda 3-8 — copy min20 wr>=0.8 hold >60 jendela 6j — tanpa TP SL0.7 60s. A: n=210 rata 0,960x menang 22,4% Wilson [17,3–28,5%] tanpa terbaik 0,937x terbaik 5,601x. B: n=8 rata 0,750x menang 0,0% Wilson [0,0–32,4%] tanpa terbaik 0,723x terbaik 0,941x.
- Bom: Bom D60 jeda 0.4 — dev belum jual top10 bebas buyer bebas mcap bebas liq>=8 smart bebas devbuy 0.5-2 holder bebas rug pembuat 0 — tahan sampai habis. A: n=34 rata 1,232x menang 26,5% Wilson [14,6–43,1%] tanpa terbaik 1,075x terbaik 6,397x. B: n=12 rata 0,614x menang 16,7% Wilson [4,7–44,8%] tanpa terbaik 0,576x terbaik 1,037x.
- Momentum: Momentum D30 jeda 0.4 — growth>=3 beli bebas dd<=15% vol bebas laju>=1.5 top10<=35% — TP3 SL0.5 120s. A: n=46 rata 1,251x menang 58,7% Wilson [44,3–71,7%] tanpa terbaik 1,214x terbaik 2,877x. B: n=19 rata 0,904x menang 42,1% Wilson [23,1–63,7%] tanpa terbaik 0,819x terbaik 2,441x.
- Sniper: Sniper dev-buy jeda 0.4 — devbuy 0.5-2 — TP1.5 SL0.9 30s. A: n=570 rata 0,941x menang 20,7% Wilson [17,6–24,2%] tanpa terbaik 0,939x terbaik 1,878x. B: n=126 rata 0,904x menang 7,9% Wilson [4,4–14,0%] tanpa terbaik 0,898x terbaik 1,619x.
- Graduation: Graduation 85% jeda 0.4 — umur >15m — trail +50% lebar 20% SL0.7 1800s. A: n=71 rata 0,977x menang 31,0% Wilson [21,4–42,5%] tanpa terbaik 0,917x terbaik 5,167x. B: n=31 rata 1,113x menang 41,9% Wilson [26,4–59,2%] tanpa terbaik 0,944x terbaik 6,172x.

## Top 10 menurut C tanpa koin terbaik
Diurut dari rata C setelah koin terbaik dibuang. Bukan hasil seleksi. Kalau n_C<30 atau A/B≤1, baris ini gagal.

### 1. Momentum D120 jeda 1 — growth>=3 beli>=65% dd<=15% vol bebas laju>=1.5 top10<=35% — TP3 SL0.7 120s
- A: n=60 rata 1,049x menang 58,3% Wilson [45,7–69,9%] tanpa terbaik 1,020x terbaik 2,785x
- B: n=12 rata 1,195x menang 50,0% Wilson [25,4–74,6%] tanpa terbaik 1,050x terbaik 2,785x
- C: n=56 rata 1,242x menang 60,7% Wilson [47,6–72,4%] tanpa terbaik 1,214x terbaik 2,786x
- p bootstrap C = 0,0050
- Simulasi $200 di C: 8% maks1 $499.71 (54 trade, menang 32); 8% maks5 $535.36 (56 trade, menang 34); 10% maks1 $611.12 (54 trade, menang 32); 10% maks5 $665.54 (56 trade, menang 34)

### 2. Momentum D120 jeda 1 — growth bebas beli>=65% dd<=15% vol>=8 laju>=1.5 top10<=35% — TP3 SL0.7 120s
- A: n=39 rata 1,003x menang 53,8% Wilson [38,6–68,4%] tanpa terbaik 0,957x terbaik 2,785x
- B: n=6 rata 1,035x menang 50,0% Wilson [18,8–81,2%] tanpa terbaik 0,799x terbaik 2,214x
- C: n=40 rata 1,249x menang 65,0% Wilson [49,5–77,9%] tanpa terbaik 1,209x terbaik 2,785x
- p bootstrap C = 0,0053
- Simulasi $200 di C: 8% maks1 $417.03 (40 trade, menang 26); 8% maks5 $417.03 (40 trade, menang 26); 10% maks1 $492.33 (40 trade, menang 26); 10% maks5 $492.33 (40 trade, menang 26)

### 3. Momentum D120 jeda 1 — growth bebas beli>=65% dd<=15% vol bebas laju>=1.5 top10<=35% — TP3 SL0.7 120s
- A: n=135 rata 0,992x menang 38,5% Wilson [30,7–46,9%] tanpa terbaik 0,978x terbaik 2,785x
- B: n=12 rata 1,195x menang 50,0% Wilson [25,4–74,6%] tanpa terbaik 1,050x terbaik 2,785x
- C: n=58 rata 1,235x menang 60,3% Wilson [47,5–71,9%] tanpa terbaik 1,208x terbaik 2,786x
- p bootstrap C = 0,0037
- Simulasi $200 di C: 8% maks1 $504.02 (56 trade, menang 33); 8% maks5 $539.98 (58 trade, menang 35); 10% maks1 $617.64 (56 trade, menang 33); 10% maks5 $672.65 (58 trade, menang 35)

### 4. Momentum D120 jeda 1 — growth>=3 beli>=65% dd<=15% vol>=8 laju>=1.5 top10<=35% — TP3 SL0.7 120s
- A: n=39 rata 1,003x menang 53,8% Wilson [38,6–68,4%] tanpa terbaik 0,957x terbaik 2,785x
- B: n=6 rata 1,035x menang 50,0% Wilson [18,8–81,2%] tanpa terbaik 0,799x terbaik 2,214x
- C: n=39 rata 1,247x menang 64,1% Wilson [48,4–77,3%] tanpa terbaik 1,207x terbaik 2,785x
- p bootstrap C = 0,0075
- Simulasi $200 di C: 8% maks1 $407.08 (39 trade, menang 25); 8% maks5 $407.08 (39 trade, menang 25); 10% maks1 $477.74 (39 trade, menang 25); 10% maks5 $477.74 (39 trade, menang 25)

### 5. Momentum D120 jeda 1 — growth>=2 beli>=65% dd<=15% vol bebas laju>=1.5 top10<=35% — TP3 SL0.7 120s
- A: n=63 rata 1,021x menang 55,6% Wilson [43,3–67,2%] tanpa terbaik 0,993x terbaik 2,785x
- B: n=12 rata 1,195x menang 50,0% Wilson [25,4–74,6%] tanpa terbaik 1,050x terbaik 2,785x
- C: n=57 rata 1,234x menang 59,6% Wilson [46,7–71,4%] tanpa terbaik 1,206x terbaik 2,786x
- p bootstrap C = 0,0053
- Simulasi $200 di C: 8% maks1 $492.00 (55 trade, menang 32); 8% maks5 $527.10 (57 trade, menang 34); 10% maks1 $599.34 (55 trade, menang 32); 10% maks5 $652.71 (57 trade, menang 34)

### 6. Momentum D120 jeda 1 — growth>=3 beli>=65% dd bebas vol>=3 laju>=1.5 top10<=35% — TP3 SL0.7 30s
- A: n=64 rata 0,990x menang 51,6% Wilson [39,6–63,4%] tanpa terbaik 0,961x terbaik 2,785x
- B: n=14 rata 1,245x menang 50,0% Wilson [26,8–73,2%] tanpa terbaik 1,126x terbaik 2,785x
- C: n=56 rata 1,219x menang 57,1% Wilson [44,1–69,2%] tanpa terbaik 1,190x terbaik 2,786x
- p bootstrap C = 0,0042
- Simulasi $200 di C: 8% maks1 $490.49 (56 trade, menang 32); 8% maks5 $490.49 (56 trade, menang 32); 10% maks1 $599.39 (56 trade, menang 32); 10% maks5 $599.39 (56 trade, menang 32)

### 7. Momentum D120 jeda 1 — growth>=3 beli>=65% dd<=15% vol bebas laju>=1.5 top10<=35% — TP3 SL0.5 120s
- A: n=60 rata 1,033x menang 58,3% Wilson [45,7–69,9%] tanpa terbaik 1,004x terbaik 2,785x
- B: n=12 rata 1,150x menang 50,0% Wilson [25,4–74,6%] tanpa terbaik 1,001x terbaik 2,785x
- C: n=56 rata 1,218x menang 60,7% Wilson [47,6–72,4%] tanpa terbaik 1,190x terbaik 2,786x
- p bootstrap C = 0,0112
- Simulasi $200 di C: 8% maks1 $446.86 (54 trade, menang 32); 8% maks5 $478.75 (56 trade, menang 34); 10% maks1 $530.33 (54 trade, menang 32); 10% maks5 $577.56 (56 trade, menang 34)

### 8. Momentum D120 jeda 1 — growth>=3 beli>=65% dd bebas vol>=3 laju>=1.5 top10<=35% — TP3 SL0.5 30s
- A: n=64 rata 0,982x menang 51,6% Wilson [39,6–63,4%] tanpa terbaik 0,954x terbaik 2,785x
- B: n=14 rata 1,257x menang 50,0% Wilson [26,8–73,2%] tanpa terbaik 1,140x terbaik 2,785x
- C: n=56 rata 1,218x menang 57,1% Wilson [44,1–69,2%] tanpa terbaik 1,189x terbaik 2,786x
- p bootstrap C = 0,0046
- Simulasi $200 di C: 8% maks1 $487.19 (56 trade, menang 32); 8% maks5 $487.19 (56 trade, menang 32); 10% maks1 $594.10 (56 trade, menang 32); 10% maks5 $594.10 (56 trade, menang 32)

### 9. Momentum D120 jeda 1 — growth>=2 beli>=65% dd bebas vol>=3 laju>=1.5 top10<=35% — TP3 SL0.7 30s
- A: n=65 rata 0,989x menang 50,8% Wilson [38,9–62,5%] tanpa terbaik 0,961x terbaik 2,785x
- B: n=14 rata 1,245x menang 50,0% Wilson [26,8–73,2%] tanpa terbaik 1,126x terbaik 2,785x
- C: n=57 rata 1,214x menang 56,1% Wilson [43,3–68,2%] tanpa terbaik 1,186x terbaik 2,786x
- p bootstrap C = 0,0044
- Simulasi $200 di C: 8% maks1 $488.39 (57 trade, menang 32); 8% maks5 $488.39 (57 trade, menang 32); 10% maks1 $596.19 (57 trade, menang 32); 10% maks5 $596.19 (57 trade, menang 32)

### 10. Momentum D120 jeda 3-8 — growth>=3 beli>=65% dd<=15% vol bebas laju>=0.5 top10<=35% — trail +50% lebar 20% SL0.7 1800s
- A: n=67 rata 0,940x menang 44,8% Wilson [33,5–56,6%] tanpa terbaik 0,923x terbaik 2,027x
- B: n=18 rata 1,068x menang 33,3% Wilson [16,3–56,3%] tanpa terbaik 0,947x terbaik 3,119x
- C: n=59 rata 1,224x menang 45,8% Wilson [33,7–58,3%] tanpa terbaik 1,172x terbaik 4,229x
- p bootstrap C = 0,0188
- Simulasi $200 di C: 8% maks1 $456.08 (54 trade, menang 25); 8% maks5 $497.84 (59 trade, menang 27); 10% maks1 $539.70 (54 trade, menang 25); 10% maks5 $600.51 (59 trade, menang 27)

## Batasan
- Signature transaksi tidak disimpan perekam GitHub. Dedupe memakai umur, 10 huruf wallet, sisi, dan SOL. Dua beli asli yang sama persis dalam 0,3 detik bisa terbuang. Dua notifikasi RPC yang umurnya terbulatkan lebih dari 0,3 detik bisa tetap dobel.
- Harga, likuiditas, holder, top10, dan inflow di snapshot berasal dari cadangan kurva (tidak ikut dobel). Rasio beli/jual di snapshot memakai jumlah event, jadi kira-kira tetap kalau kedua sisi dobel, tetapi tidak persis.
- Volume di candle (bukan yang dipakai filter) bisa dobel. Filter volume memakai selisih inflow snapshot.
- Riwayat rug pembuat hanya sejak perekam berjalan, bukan seluruh riwayat on-chain.
- Wallet pintar / copy hanya dari trade 5 menit pertama, maks 150 per koin, wallet terpotong 10 huruf.
- Harga setelah lulus ke PumpSwap tidak ada. Graduation berhenti di ujung rekaman (batas atas).
- Sampel, kalau jumlah koin standar melebihi --sample, diambil merata dari yang paling lama sampai yang paling baru.
- Biaya berat (fee+slippage+priority+dampak kurva). Isi stop candle x0,72.
- Waktu hitung statistik+null: 4919 detik. Total skrip: 4919 detik.

Paper saja. Jangan dipakai live karena protokol ini belum menemukan edge yang mengalahkan kebetulan dan koreksi uji berganda.

## Holdout: koin di luar sampel 30.000

Aturan dikunci sebelum uji ini. Tidak ada ambang yang digeser. Pembagian A/B/C 50/20/30 dihitung ulang hanya pada koin holdout, urut waktu lahir.
- Koin standar: 135797. Sampel lama: 30000. Holdout: 105797.
- A/B/C holdout: 52898/21159/31740.
- Periode holdout: 27 Oct 2026 00:00 UTC / 07:00 WIB – 10 Nov 2026 07:16 UTC / 14:16 WIB.
- Potongan: 02 Nov 2026 17:43 UTC / 00:43 WIB / 05 Nov 2026 16:55 UTC / 23:55 WIB.
- Riwayat wallet pintar dihitung dulu pada semua koin standar, baru koin sampel dibuang dari skor.

| Aturan | Irisan | n | Rata | Menang (Wilson) | Tanpa terbaik | $200 8% maks1 | 8% maks5 | 10% maks1 | 10% maks5 |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|
| (a) Momentum, baris 1 top-10 C tanpa koin terbaik | | | | | | | | | |
| D120 jeda 1 dtk, growth≥3, drawdown≤35%, top10≤35%, beli/vol/laju bebas, parsial 50% di 2x sisa TP5 SL0,7 600 dtk | | | | | | | | | |
| | A | 143 | 1,001x | 44,1% [36,2–52,2%] | 0,985x | $204 (124) | $174 (143) | $197 (124) | $161 (143) |
| | B | 49 | 1,097x | 28,6% [17,8–42,4%] | 0,961x | $257 (47) | $248 (49) | $262 (47) | $250 (49) |
| | C | 110 | 1,013x | 36,4% [28,0–45,7%] | 0,983x | $205 (92) | $185 (110) | $197 (92) | $171 (110) |
| | gagal syarat C | ya | | | | | | | |
| (b) Momentum terbaik menurut A pada sampel | | | | | | | | | |
| D120 jeda 3–8 dtk, growth≥3, rasio beli≥65%, inflow baru≥3 SOL, laju pembeli≥1,5, parsial 50% di 2x sisa TP5 SL0,7 600 dtk | | | | | | | | | |
| | A | 183 | 1,014x | 49,7% [42,6–56,9%] | 1,002x | $168 (156) | $191 (183) | $151 (156) | $175 (183) |
| | B | 39 | 1,152x | 46,2% [31,6–61,4%] | 1,097x | $294 (35) | $294 (39) | $317 (35) | $316 (39) |
| | C | 97 | 1,032x | 42,3% [32,9–52,2%] | 1,009x | $155 (91) | $214 (97) | $139 (91) | $207 (97) |
| | gagal syarat C | tidak | | | | | | | |
| (c) Bom terbaik menurut A pada sampel | | | | | | | | | |
| D180 jeda 1 dtk, dev belum jual, top10≤40%, buyer≥40, liq≥8, smart≥1, devbuy<0,5, rug pembuat 0, TP3 SL0,5 600 dtk | | | | | | | | | |
| | A | 185 | 0,866x | 24,3% [18,7–31,0%] | 0,856x | $29 (153) | $22 (185) | $17 (153) | $12 (185) |
| | B | 92 | 0,837x | 25,0% [17,3–34,7%] | 0,815x | $59 (81) | $53 (92) | $42 (81) | $37 (92) |
| | C | 144 | 0,818x | 20,8% [15,0–28,2%] | 0,804x | $38 (118) | $20 (144) | $24 (118) | $11 (144) |
| | gagal syarat C | ya | | | | | | | |
| (d) Graduation 98%, umur di bawah 5 menit | | | | | | | | | |
| kurva 98%, umur sinyal <5 menit, jeda 3–8 dtk, tahan sampai rekaman habis | | | | | | | | | |
| | A | 244 | 0,893x | 2,9% [1,4–5,8%] | 0,887x | $29 (201) | $24 (244) | $18 (201) | $14 (244) |
| | B | 61 | 0,938x | 8,2% [3,6–17,8%] | 0,891x | $147 (55) | $143 (61) | $135 (55) | $130 (61) |
| | C | 150 | 0,918x | 8,7% [5,1–14,3%] | 0,903x | $100 (130) | $72 (150) | $83 (130) | $55 (150) |
| | gagal syarat C | ya | | | | | | | |

Syarat gagal di C: n<30, atau rata ≤1, atau rata tanpa koin terbaik ≤1. Simulasi $200 memakai kelipatan bersih urut waktu pada irisan itu saja.
