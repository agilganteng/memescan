TIDAK LAYAK. 2160504 kombinasi, lulus ekonomi 308, null rata-rata 0,00 (maks 0,0). Finalis protokol A→B→C yang lolos syarat: 0. Tidak ada yang lolos koreksi uji berganda atas seluruh pencarian.

# Riset grid luas strategi pump.fun, 10 Nov 2026, PAPER

Bukan saran beli. Tidak ada kunci, tidak ada transaksi.

## Data
- Kunci cache: `memescan-data-42685043176`
- Berkas: 15 file rec, 351456 baris, 286987 punya trade wallet.
- Periode rekaman (t0 pertama–terakhir): 27 Oct 2026 00:00 UTC / 07:00 WIB – 10 Nov 2026 07:17 UTC / 14:17 WIB.
- Koin kurva standar: 135797. Yang diuji (sampel merata waktu, kalau dipotong): 30000.
- Periode yang diuji: 27 Oct 2026 00:00 UTC / 07:00 WIB – 10 Nov 2026 07:17 UTC / 14:17 WIB.
- Potongan A/B/C: 02 Nov 2026 17:44 UTC / 00:44 WIB / 05 Nov 2026 16:55 UTC / 23:55 WIB.
- Jumlah koin A/B/C: 15000/6000/9000.
- Dedupe: 8353665 baris trade dibuang di 281776 koin (kunci wallet+sisi+SOL, selisih umur ≤0,3 dtk). Signature tidak ada di rekaman.
- Hash skrip sha256: `b15f84f0abde40a1e6aa800ae137668cb08a3c48e5d70dcfb570950d75efe8f2`

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
| Sniper | 630 | 0 | 0,00 | 0,0 |
| Bom | 1741824 | 0 | 0,00 | 0,0 |
| Momentum | 408240 | 308 | 0,00 | 0,0 |
| Graduation | 2520 | 0 | 0,00 | 0,0 |
| Copy | 7290 | 0 | 0,00 | 0,0 |

Total kombinasi 2160504. Total lulus ekonomi 308.
Null global (20): 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.
Null rata 0,00, maks 0,0.

## Lima teratas menurut A (seleksi resmi)

### 1. Momentum D120 jeda 3-8 — growth>=3 beli>=65% dd bebas vol>=3 laju>=1.5 top10 bebas — parsial 50% 2x sisa TP5 SL0.7 600s
- A: n=51 rata 1,269x menang 54,9% Wilson [41,4–67,7%] tanpa terbaik 1,230x terbaik 3,250x
- B: n=12 rata 0,919x menang 58,3% Wilson [32,0–80,7%] tanpa terbaik 0,826x terbaik 1,944x
- C: tidak diuji (gagal di B, atau B tidak di atas 1).

### 2. Momentum D120 jeda 3-8 — growth bebas beli>=65% dd bebas vol>=3 laju>=1.5 top10 bebas — parsial 50% 2x sisa TP5 SL0.7 600s
- A: n=52 rata 1,263x menang 53,8% Wilson [40,5–66,7%] tanpa terbaik 1,224x terbaik 3,250x
- B: n=12 rata 0,919x menang 58,3% Wilson [32,0–80,7%] tanpa terbaik 0,826x terbaik 1,944x
- C: tidak diuji (gagal di B, atau B tidak di atas 1).

### 3. Momentum D120 jeda 3-8 — growth>=3 beli>=65% dd<=35% vol bebas laju>=1.5 top10 bebas — parsial 50% 2x sisa TP5 SL0.7 600s
- A: n=58 rata 1,251x menang 53,4% Wilson [40,8–65,7%] tanpa terbaik 1,216x terbaik 3,250x
- B: n=16 rata 0,810x menang 43,8% Wilson [23,1–66,8%] tanpa terbaik 0,734x terbaik 1,944x
- C: tidak diuji (gagal di B, atau B tidak di atas 1).

### 4. Momentum D120 jeda 3-8 — growth>=3 beli>=65% dd bebas vol>=3 laju>=1.5 top10 bebas — TP3 SL0.7 600s
- A: n=51 rata 1,243x menang 52,9% Wilson [39,5–65,9%] tanpa terbaik 1,212x terbaik 2,792x
- B: n=12 rata 0,811x menang 41,7% Wilson [19,3–68,0%] tanpa terbaik 0,699x terbaik 2,037x
- C: tidak diuji (gagal di B, atau B tidak di atas 1).

### 5. Momentum D120 jeda 3-8 — growth>=3 beli>=65% dd<=15% vol bebas laju>=1.5 top10 bebas — parsial 50% 2x sisa TP5 SL0.7 600s
- A: n=49 rata 1,242x menang 53,1% Wilson [39,4–66,3%] tanpa terbaik 1,201x terbaik 3,250x
- B: n=13 rata 0,919x menang 53,8% Wilson [29,1–76,8%] tanpa terbaik 0,834x terbaik 1,944x
- C: tidak diuji (gagal di B, atau B tidak di atas 1).

## Terbaik di A per keluarga (C tidak dibuka di sini)

- Sniper: Sniper dev-buy jeda 0.4 — devbuy 0.5-2 — TP1.5 SL0.9 30s. A: n=132 rata 0,947x menang 21,2% Wilson [15,1–28,9%] tanpa terbaik 0,943x terbaik 1,566x. B: n=35 rata 0,900x menang 8,6% Wilson [3,0–22,4%] tanpa terbaik 0,895x terbaik 1,063x.
- Bom: Bom D180 jeda 1 — dev belum jual top10<=40% buyer>=40 mcap bebas liq>=8 smart>=1 devbuy<0.5 holder bebas rug pembuat 0 — TP3 SL0.5 600s. A: n=50 rata 1,136x menang 40,0% Wilson [27,6–53,8%] tanpa terbaik 1,103x terbaik 2,793x. B: n=18 rata 0,887x menang 11,1% Wilson [3,1–32,8%] tanpa terbaik 0,775x terbaik 2,791x.
- Momentum: Momentum D120 jeda 0.4 — growth>=2 beli>=65% dd<=35% vol>=3 laju>=1.5 top10 bebas — parsial 50% 2x sisa TP5 SL0.7 600s. A: n=51 rata 1,269x menang 54,9% Wilson [41,4–67,7%] tanpa terbaik 1,230x terbaik 3,250x. B: n=12 rata 0,919x menang 58,3% Wilson [32,0–80,7%] tanpa terbaik 0,826x terbaik 1,944x.
- Graduation: Graduation 85% jeda 0.4 — umur 5-15m — TP3 SL0.5 120s. A: n=41 rata 0,986x menang 43,9% Wilson [29,9–59,0%] tanpa terbaik 0,942x terbaik 2,785x. B: n=14 rata 0,908x menang 28,6% Wilson [11,7–54,6%] tanpa terbaik 0,887x terbaik 1,171x.
- Copy: Copy-wallet jeda 0.4 — copy min20 wr>=0.8 hold semua jendela 6j — ikut jual SL0.7. A: n=30 rata 0,997x menang 46,7% Wilson [30,2–63,9%] tanpa terbaik 0,983x terbaik 1,397x. B: n=0.

## Top 10 menurut C tanpa koin terbaik
Diurut dari rata C setelah koin terbaik dibuang. Bukan hasil seleksi. Kalau n_C<30 atau A/B≤1, baris ini gagal.

### 1. Momentum D120 jeda 1 — growth>=3 beli bebas dd<=35% vol bebas laju bebas top10<=35% — parsial 50% 2x sisa TP5 SL0.7 600s
- A: n=39 rata 1,047x menang 33,3% Wilson [20,6–49,0%] tanpa terbaik 0,990x terbaik 3,249x
- B: n=18 rata 0,991x menang 27,8% Wilson [12,5–50,9%] tanpa terbaik 0,859x terbaik 3,250x
- C: n=30 rata 1,495x menang 46,7% Wilson [30,2–63,9%] tanpa terbaik 1,242x terbaik 8,813x
- p bootstrap C = 0,0335
- Simulasi $200 di C: 8% maks1 $518.92 (30 trade, menang 14); 8% maks5 $518.92 (30 trade, menang 14); 10% maks1 $622.55 (30 trade, menang 14); 10% maks5 $622.55 (30 trade, menang 14)

### 2. Momentum D120 jeda 1 — growth>=3 beli bebas dd<=35% vol bebas laju bebas top10<=35% — parsial 50% 1.5x sisa TP5 SL0.7 600s
- A: n=39 rata 1,027x menang 30,8% Wilson [18,6–46,4%] tanpa terbaik 0,974x terbaik 3,016x
- B: n=18 rata 0,990x menang 11,1% Wilson [3,1–32,8%] tanpa terbaik 0,871x terbaik 3,016x
- C: n=30 rata 1,465x menang 43,3% Wilson [27,4–60,8%] tanpa terbaik 1,212x terbaik 8,813x
- p bootstrap C = 0,0350
- Simulasi $200 di C: 8% maks1 $493.30 (30 trade, menang 13); 8% maks5 $493.30 (30 trade, menang 13); 10% maks1 $587.68 (30 trade, menang 13); 10% maks5 $587.68 (30 trade, menang 13)

### 3. Momentum D120 jeda 1 — growth>=3 beli bebas dd<=35% vol bebas laju bebas top10<=35% — trail +100% lebar 20% SL0.7 1800s
- A: n=39 rata 0,860x menang 25,6% Wilson [14,6–41,1%] tanpa terbaik 0,829x terbaik 2,027x
- B: n=18 rata 1,130x menang 33,3% Wilson [16,3–56,3%] tanpa terbaik 0,904x terbaik 4,962x
- C: n=30 rata 1,451x menang 40,0% Wilson [24,6–57,7%] tanpa terbaik 1,197x terbaik 8,813x
- p bootstrap C = 0,0713
- Simulasi $200 di C: 8% maks1 $456.13 (30 trade, menang 12); 8% maks5 $456.13 (30 trade, menang 12); 10% maks1 $527.23 (30 trade, menang 12); 10% maks5 $527.23 (30 trade, menang 12)

### 4. Momentum D120 jeda 1 — growth>=3 beli bebas dd<=35% vol bebas laju bebas top10<=35% — TP3 SL0.7 600s
- A: n=39 rata 1,056x menang 33,3% Wilson [20,6–49,0%] tanpa terbaik 1,010x terbaik 2,793x
- B: n=18 rata 0,850x menang 11,1% Wilson [3,1–32,8%] tanpa terbaik 0,736x terbaik 2,785x
- C: n=30 rata 1,435x menang 43,3% Wilson [27,4–60,8%] tanpa terbaik 1,181x terbaik 8,813x
- p bootstrap C = 0,0549
- Simulasi $200 di C: 8% maks1 $456.13 (30 trade, menang 13); 8% maks5 $456.13 (30 trade, menang 13); 10% maks1 $531.61 (30 trade, menang 13); 10% maks5 $531.61 (30 trade, menang 13)

### 5. Momentum D120 jeda 1 — growth>=3 beli bebas dd<=35% vol bebas laju bebas top10<=35% — trail +50% lebar 20% SL0.7 1800s
- A: n=39 rata 0,876x menang 23,1% Wilson [12,6–38,3%] tanpa terbaik 0,845x terbaik 2,027x
- B: n=18 rata 1,157x menang 33,3% Wilson [16,3–56,3%] tanpa terbaik 0,933x terbaik 4,962x
- C: n=30 rata 1,435x menang 40,0% Wilson [24,6–57,7%] tanpa terbaik 1,180x terbaik 8,813x
- p bootstrap C = 0,0740
- Simulasi $200 di C: 8% maks1 $444.59 (30 trade, menang 12); 8% maks5 $444.59 (30 trade, menang 12); 10% maks1 $512.60 (30 trade, menang 12); 10% maks5 $512.60 (30 trade, menang 12)

### 6. Momentum D120 jeda 1 — growth>=3 beli bebas dd<=35% vol bebas laju bebas top10<=35% — trail +100% lebar 20% SL0.7 300s
- A: n=39 rata 0,890x menang 28,2% Wilson [16,5–43,8%] tanpa terbaik 0,847x terbaik 2,546x
- B: n=18 rata 1,137x menang 27,8% Wilson [12,5–50,9%] tanpa terbaik 0,912x terbaik 4,962x
- C: n=30 rata 1,428x menang 43,3% Wilson [27,4–60,8%] tanpa terbaik 1,173x terbaik 8,813x
- p bootstrap C = 0,0765
- Simulasi $200 di C: 8% maks1 $437.69 (30 trade, menang 13); 8% maks5 $437.69 (30 trade, menang 13); 10% maks1 $502.58 (30 trade, menang 13); 10% maks5 $502.58 (30 trade, menang 13)

### 7. Momentum D120 jeda 1 — growth>=2 beli bebas dd<=35% vol bebas laju>=0.5 top10<=35% — parsial 50% 2x sisa TP5 SL0.7 600s
- A: n=49 rata 0,961x menang 30,6% Wilson [19,5–44,5%] tanpa terbaik 0,913x terbaik 3,249x
- B: n=19 rata 0,905x menang 31,6% Wilson [15,4–54,0%] tanpa terbaik 0,775x terbaik 3,250x
- C: n=40 rata 1,214x menang 45,0% Wilson [30,7–60,2%] tanpa terbaik 1,162x terbaik 3,250x
- p bootstrap C = 0,0756
- Simulasi $200 di C: 8% maks1 $355.56 (38 trade, menang 18); 8% maks5 $352.91 (40 trade, menang 18); 10% maks1 $397.15 (38 trade, menang 18); 10% maks5 $393.44 (40 trade, menang 18)

### 8. Momentum D120 jeda 1 — growth>=3 beli bebas dd<=35% vol bebas laju bebas top10<=35% — TP3 SL0.7 120s
- A: n=39 rata 1,060x menang 35,9% Wilson [22,7–51,6%] tanpa terbaik 1,015x terbaik 2,785x
- B: n=18 rata 1,028x menang 27,8% Wilson [12,5–50,9%] tanpa terbaik 0,924x terbaik 2,785x
- C: n=30 rata 1,416x menang 53,3% Wilson [36,1–69,8%] tanpa terbaik 1,161x terbaik 8,813x
- p bootstrap C = 0,0532
- Simulasi $200 di C: 8% maks1 $443.86 (30 trade, menang 16); 8% maks5 $443.86 (30 trade, menang 16); 10% maks1 $516.43 (30 trade, menang 16); 10% maks5 $516.43 (30 trade, menang 16)

### 9. Momentum D120 jeda 1 — growth>=3 beli bebas dd<=35% vol bebas laju bebas top10<=35% — trail +50% lebar 20% SL0.7 300s
- A: n=39 rata 0,902x menang 28,2% Wilson [16,5–43,8%] tanpa terbaik 0,859x terbaik 2,546x
- B: n=18 rata 1,137x menang 27,8% Wilson [12,5–50,9%] tanpa terbaik 0,912x terbaik 4,962x
- C: n=30 rata 1,412x menang 43,3% Wilson [27,4–60,8%] tanpa terbaik 1,156x terbaik 8,813x
- p bootstrap C = 0,0804
- Simulasi $200 di C: 8% maks1 $426.61 (30 trade, menang 13); 8% maks5 $426.61 (30 trade, menang 13); 10% maks1 $488.63 (30 trade, menang 13); 10% maks5 $488.63 (30 trade, menang 13)

### 10. Momentum D120 jeda 1 — growth>=3 beli bebas dd bebas vol bebas laju bebas top10<=35% — parsial 50% 2x sisa TP5 SL0.7 600s
- A: n=41 rata 1,050x menang 34,1% Wilson [21,6–49,5%] tanpa terbaik 0,995x terbaik 3,249x
- B: n=20 rata 1,028x menang 30,0% Wilson [14,5–51,9%] tanpa terbaik 0,911x terbaik 3,250x
- C: n=35 rata 1,373x menang 40,0% Wilson [25,6–56,4%] tanpa terbaik 1,155x terbaik 8,813x
- p bootstrap C = 0,0653
- Simulasi $200 di C: 8% maks1 $449.09 (35 trade, menang 14); 8% maks5 $449.09 (35 trade, menang 14); 10% maks1 $519.16 (35 trade, menang 14); 10% maks5 $519.16 (35 trade, menang 14)

## Batasan
- Signature transaksi tidak disimpan perekam GitHub. Dedupe memakai umur, 10 huruf wallet, sisi, dan SOL. Dua beli asli yang sama persis dalam 0,3 detik bisa terbuang. Dua notifikasi RPC yang umurnya terbulatkan lebih dari 0,3 detik bisa tetap dobel.
- Harga, likuiditas, holder, top10, dan inflow di snapshot berasal dari cadangan kurva (tidak ikut dobel). Rasio beli/jual di snapshot memakai jumlah event, jadi kira-kira tetap kalau kedua sisi dobel, tetapi tidak persis.
- Volume di candle (bukan yang dipakai filter) bisa dobel. Filter volume memakai selisih inflow snapshot.
- Riwayat rug pembuat hanya sejak perekam berjalan, bukan seluruh riwayat on-chain.
- Wallet pintar / copy hanya dari trade 5 menit pertama, maks 150 per koin, wallet terpotong 10 huruf.
- Harga setelah lulus ke PumpSwap tidak ada. Graduation berhenti di ujung rekaman (batas atas).
- Sampel, kalau jumlah koin standar melebihi --sample, diambil merata dari yang paling lama sampai yang paling baru.
- Biaya berat (fee+slippage+priority+dampak kurva). Isi stop candle x0,72.
- Waktu hitung statistik+null: 568 detik. Total skrip: 692 detik.

Paper saja. Jangan dipakai live karena protokol ini belum menemukan edge yang mengalahkan kebetulan dan koreksi uji berganda.
