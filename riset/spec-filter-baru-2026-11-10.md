# Praregistrasi: modul filter baru calon Bom v2 — 10 Nov 2026

**Status:** PRA-REGISTRASI. Ditulis 10 Nov 2026 ±18:35 WIB, SEBELUM ada run backtest baru. Tidak ada GitHub Actions yang di-dispatch dari dokumen ini. Bom v1, mom120, forward-narasi, dan file terkunci tidak diubah.

**Tujuan:** kumpulkan filter dari video yang user kirim, dari checklist publik X/web, dan dari ide user (beli koin yang bukan cuma baru listing selama mcap masih di bawah ambang; anti-rug; anti-honeypot), lalu petakan ke satu bot Bom (tim 5 agent + Guard). Modul hanya boleh masuk Bom v2 kalau lulus protokol di bawah. Klaim profit di video/X diabaikan.

Paper only. Bukan sinyal live.

---

## 1. Cara masuk ke voting Bom

Satu bot, lima agent (rug, narasi, latar, data, whale). Bom yang memutuskan entry/exit.

- Vote **4/5** (usulan user) dan **5/5** (cara video nfp: satu tolak = SKIP) diuji berdampingan.
- Agent yang telat 1–3 dtk tetap ditunggu. Setelah vote ACC, entry hanya jika harga masih di dalam pita vs harga cek pertama (pita kandidat: ±10 / ±15 / ±25 / tanpa pita). Kalau sudah terbang atau anjlok melewati pita: SKIP.
- **Guard** (exit, bukan voter entry): memantau posisi terus-menerus, seperti Guard di video nfp.
- Modul baru **bukan bot terpisah**. Tiap modul menempel ke satu agent sebagai aturan pass/fail + alasan yang bisa ditampilkan di dashboard (lulus/tolak + alasan, persis gaya video).
- Narasi X tetap tidak bisa diuji jujur di data lama (sudah terbukti di riset Bom v2). Di backtest, narasi diuji sebagai dua skenario yang sudah dikunci: (N-skip) narasi selalu SKIP, (N-yes) narasi selalu ACC. Jangan di-tuning dari hasil.

Cara menempel:

| Peran modul | Agent | Efek di 4/5 | Efek di 5/5 |
|---|---|---|---|
| Hard filter keamanan (anti-rug, anti-honeypot, mint/freeze, T22 berbahaya) | rug | 1 suara. Gagal = rug menolak. Kalau rug null (fail-closed), hitung sebagai bukan ACC | 1 gagal = SKIP seluruh koin |
| Latar dev/bundle/fresh/copycat | latar | 1 suara | sama |
| Data pasar (mcap/umur/liq/+100% 1j/kurva) | data | 1 suara | sama |
| Konfirmasi whale/copy | whale | 1 suara ACC hanya jika wallet target beli (atau ≥k wallet) sebelum keputusan; kalau tidak terlihat = SKIP/abstain sesuai varian | sama |
| Narasi | narasi | 1 suara, dua skenario di atas | sama |
| Exit | Guard | tidak ikut vote entry | — |

Varian gabungan yang diuji (dikunci sekarang): modul hard rug wajib di kedua mode; modul data/latar/whale ditambah satu-satu dan dalam paket "semua hard + mcap-umur + whale confirm". Jangan menggabungkan 68 juta kombinasi lagi tanpa Bonferroni.

---

## 2. Video yang user kirim, dan aturan konkretnya

Sumber di disk: `riset/nfp-*`, `riset/video-bevan`, `riset/reactorworld-*`, `riset/onchainlyfe-*`, `riset/zostaff-*`, `/workspace/reel`, `/workspace/shotgun-video-example`. Klaim PnL di layar diabaikan (promo / animasi / paper).

### 2.1 TikTok @nfp.paid / 7701793226818129158 (28 Okt 2026, 27 dtk) — model dashboard Bom

Funnel: Scout (512 "smart wallet") → Filter (hard rules) → Analyst (deep, 6/6) → Sniper (eksekusi) → Guard (stop). Satu tolak = skip, plus alasan di log.

Alasan skip yang tertulis di layar ("Why signals got skipped") + log:

| Aturan | Di video | Agent Bom |
|---|---|---|
| Dev wallet > 5% | Filter + Analyst | latar (utama), rug cadangan |
| Top 10 holders > 35% | Filter | rug / data |
| Already +100% 1h | Filter | data |
| Liquidity under $25k | Filter | data / rug |
| Bundled buys | Filter | latar |
| LP not locked / LP unlocked | Filter | rug (hanya setelah lulus DEX; di kurva pump.fun tidak ada LP) |
| Wallet WR < 55% | Filter (`wallet WR <55%`) | whale (buku wallet) |
| Fresh wallets / "fresh wallets only" | Analyst | latar |
| Dev sold 40% | Analyst | latar |
| Guard hard stop −8% | Guard (`stop -8%`, "stop where rules said") | Guard |
| Scout: copy saat smart wallet beli | Scout | whale |

Catatan jujur: koin di layar sudah mcap besar (REMUS $1.85M, LAUNCH $1.70M, NOTHING $707K), bukan hanya listing baru. Filter liq < $25k praktis menolak hampir semua koin yang masih di bonding curve (likuiditas riil kurva << $25k sampai dekat lulus). "6/6 rules" Analyst tidak pernah didaftar lengkap; yang terlihat cuma fresh wallets dan dev sold 40%, plus tumpang tindih dengan Filter. Equity $100→naik di video adalah tampilan, bukan bukti.

### 2.2 File `/workspace/reel/x1.mp4` (Grok "ISSA TERMINAL", tanpa caption terpisah)

Tampilan lain bot Grok: koin baru di pump.fun, umur 8 dtk, mcap $9.6K. Chip rug check: **dev 38% = X (tolak)**, **bundles 7% = lulus**. Klaim saldo $600→$813 diabaikan. Aturan yang bisa ditiru: entry umur detik, mcap rendah, tolak dev tinggi, bundle % sebagai chip.

### 2.3 Instagram @aitechdaily.hub / Dfc0f-US9_R (`/workspace/reel/reel.mp4`, 7 Nov 2026)

Promo "I LET GROK TRADE WHILE I SLEPT", klaim $125→$3,875 / 62 entry. Tidak ada aturan filter yang terbaca di metadata. Tidak dipakai sebagai aturan.

### 2.4 `/workspace/reel/x3.mp4`

Layar deposit FOMO $20 (Apple Pay). Tidak ada filter. Tidak dibuka lebih jauh (aplikasi beli).

### 2.5 TikTok @bevanpramudt / 7706134418632510741 + bedahan semua konten Bevan (strategi-bevan-2026-11-07.md)

Video pendek: "be as early as possible"; bukan wallet Solana (alamat di layar = token e/acc di Elysium). Checklist anti-rug gabungan podcast/video yang bisa dijadikan modul:

1. Rekam jejak dev (pernah run / pernah rug)
2. Bundle / linked / 10 tx pertama dari sumber dana sama
3. % supply di 10 dtk pertama / 50 wallet pertama / bot first buy
4. Bundle atau deployer sudah jual berapa %
5. Holder didominasi fresh wallet
6. Holder banyak, top10 kecil, tim tidak pegang banyak
7. Likuiditas, slippage, cek honeypot (sell tax)
8. Lebih aman di pump.fun/bonk daripada koin Raydium "biasa" (risiko honeypot)
9. Hindari endorse KOL / PvP ticker kembar
10. Swing: koin umur 1–3 hari yang masih hidup; snipe dev langganan di MC <$50–90k; nyendal dulu
11. Exit: tim/wallet panutan mulai jual; cut sekitar −30% (ada kontradiksi antar videonya: kadang "hold to zero")

**Sudah diuji OOS 7 Nov (run 42402319399, 248.913 koin):** checklist "persis Bevan" n=16 (kurang), tetap rugi (0,76–0,85x). Grid 38.880 varian: 0 yang untung di A dan B. Snipe dev langganan rugi, termasuk jeda 0,4 dtk. Jangan diuji ulang dengan ambang yang sama. Yang boleh diuji ulang hanya ide yang **benar-benar beda**: jendela umur 30–60 menit atau 1–3 hari (tidak ada di tes itu, karena rec cuma 10–30 menit), atau mode "koin lama masih di bawah mcap X".

### 2.6 TikTok @reactorworld / 7680128832883707157 (31 Agu 2026)

Promo aplikasi FOMO: follow whale @DumbCrayonEater, notifikasi beli, eksekusi Buy. Contoh di video: CETS sudah di MC $19.1M dan +1,265% saat "demo beli". Tidak ada arsitektur multi-agen, tidak ada alamat Solana. Aturan yang tersisa: copy-whale + jangan beli yang sudah terbang — itu sudah masuk filter "+100% 1h" dan pita harga. Link bio tidak dibuka.

### 2.7 TikTok @onchainlyfe.xyz / 7683352939875896593 (9 Sep 2026)

Promo PnL trader @cryptoalbus di FOMO. Caption: entry $821 di $MEME pada MC $40,7k. Tidak ada aturan bot, angka di layar tidak konsisten. Dipakai hanya sebagai **satu titik data mcap entry ~$40k**, bukan strategi.

### 2.8 X @zostaff / 2118830758810821103 (7 Nov 2026)

Tujuh bot: monitor launch, sniper entry pertama, copy wallet pemenang, **graduation sniper di kurva 92%**, analyzer lawan. Klaim 5 wallet terbaik dari 666: tanpa program kustom, CU price 0, WR 80%. Exit sniper demo: **2x, −50%, atau 120 dtk**. Verdict: promo + dry-run. **Sudah diuji** (zgrid, 467.130 varian, 10 Nov): finalis 0, yang "lulus" = null. Graduation 50–98% tidak cukup n di data 65 menit; di data 8 Nov (118.173 koin) semua keluarga rugi. Jangan diuji ulang grid yang sama. Boleh jadi kandidat **hanya jika** digabung ke agent data/whale sebagai satu modul dengan ambang yang sudah ada, di protokol A+B yang bersih, bukan grid ratusan ribu.

---

## 3. Tips publik X/web (10 Nov 2026, kuota X tersisa 884/1000 setelah 4 panggilan baca)

Sumber web: pumpfyi.com/coin, trenchbay scanner, docs memeperfect strategy editor, pumpapi.io detect_scam_tokens. Sumber X (bukan referral, tidak dibuka tautan Telegram):

- @stpete69 5 Nov 2026 (https://x.com/stpete69/status/2118250609413706072): 60 dtk anti-rug, 1 gagal = skip — mint off, freeze off, LP locked/burned, top10 < 30%, quote jual kecil Jupiter harus bisa, volume bukan wash.
- @ism_sol 29 Okt 2026 (https://x.com/ism_sol/status/2115634239031140370): checklist 3 menit, 1 merah = skip; mulai dari Rugcheck (score/risks, mint authority). Gambar lampiran hanya grafis "1 red · skip", isi lengkap terpotong di teks.
- @degenapps_ 1 Nov, @ogrobinhoodog 29 Okt, @cvele_onchain_ 21 Okt, @Knightcatfans 28 Okt: inti yang sama (mint/freeze, LP, top10, dev jual, liq vs mcap, top10 jangan dari funding sama). Boost DexScreener = iklan berbayar, bukan aman.

Tidak ada daftar alamat whale lengkap yang diposting terang-terangan di hasil pencarian X ini. Yang ketemu mayoritas checklist atau promo scanner.

---

## 4. Data yang benar-benar ada (jujur)

| Sumber | Isi | Batas |
|---|---|---|
| Rekaman memescan `rec-*.jsonl` (cache Actions `memescan-data-*`, branch main) | Koin pump.fun bonding curve. Snapshot umur 10,20,30,45,60,90,120,180,300,600 dtk: mcap, inflow, unique buyers, holders, top10/top20, dev_pct, dev_sold_any, creator_prev_tokens/rugs, bundle, liq, growth, drawdown, buy/sell ratio. Candle s/d 30 menit. Wallet trade s/d umur 5 menit, **hanya 10 karakter pertama**, maks 150 baris/koin | Bukan USD asli: mcap/liq di rec = satuan SOL (mcap_sol × SOL/USD). Tidak ada mint/freeze, T22, quote Jupiter, LP lock, narasi X, funding hop, CU price, program kustom. Umur >30 menit tidak ada. Cache tidak bisa diunduh dari box; tes besar harus di Actions nanti (bukan sekarang) |
| Rec lokal box | `zgrid/data/rec/rec-20261110.jsonl` dan `riset/zostaff-grid/rec-20261110-box.jsonl`: 10 Nov 13:23–14:28 WIB (~65 menit, 843 baris, 765 ada wallet), ada gap ~10 menit | Terlalu pendek untuk n≥30 per pita umur 30–60 menit. Boleh untuk cek kode, bukan untuk lulus resmi |
| `lulus-data-*` / `riset/data/tokens.json` (717 lulusan 8–9 Nov) + sebagian OHLCV GeckoTerminal | mcap0, liq0 saat deteksi lulus; harga 1 menit setelah lulus | Jendela ~23 jam. Graduation snipe dan koin pasca-lulus. Umur 1–3 hari hampir tidak ada |
| `desk/whale_data/trades` | 683.991 trade PumpSwap/DEX, 1.565 mint, alamat wallet **lengkap**, 8 Nov 11:40 UTC → 10 Nov 11:25 UTC | Bukan kurva bonding. Bagus untuk mencocokkan whale, bukan untuk snipe detik-detik awal |
| Modul live `rug.py` / `latar.py` / `data.py` | Authority, T22, rugcheck, quote Jupiter, bundle/dev history, liq/mcap DexScreener | State **saat ini**. Re-run ke koin lama = lookahead. Untuk backtest hanya pakai field yang terekam saat sinyal |

**Potongan waktu (wajib):** tuning hanya di **A+B**. Potong A/B di **2 Nov 17:43 UTC** dan akhir B di **5 Nov 16:55 UTC**. Slice C set lama **terkontaminasi** (sudah diintip di riset Bom v2) — jangan dipakai pilih parameter, jangan dijadikan bukti lulus.

**Konfirmasi bersih:** hanya di data recorder dengan `t0` **setelah 10 Nov 07:17 UTC**, dan hanya jika ada cache/artifact `memescan-data-*` yang lebih baru dari cache 10 Nov 14:17 WIB (= 07:17 UTC). Saat spek ini ditulis, cache itu belum ada di box. Kalau belum ada cache lebih baru, konfirmasi ditunda — jangan memaksa pakai C lama.

**Biaya & eksekusi (backtest-oos):** jeda acak 3–8 dtk (tampilkan juga 1 dtk dan 0,4 dtk sebagai batas atas, bukan andalan). Fee 1,25%/sisi, slippage 2%/sisi, priority 0,0005 SOL ×2, dampak kurva. Dalam satu candle: turun dulu baru naik. Stop dari candle ×0,72. Buang kurva non-standar secara kausal (`deep.load(..., floor='std')`).

**Simulasi:** $200 (tampilkan juga $100 dan $1000). Ukuran 8% dan 10% saldo/trade, urut waktu, maks 1 dan maks 5 posisi. n_B ≥ 30, mean A > 1, mean B > 1, mean B tanpa koin terbaik > 1, jumlah lulus > null 20-shuffle (Bonferroni atau bandingkan ke sebaran null). Wilson CI 95%, PF, mean/median x, winrate.

---

## 5. Vonis honeypot

**Di bonding curve pump.fun, honeypot klasik (beli bisa, jual tidak bisa) pada dasarnya tidak berlaku.** Jual dilayani program kurva. Koin pump.fun diluncurkan dengan mint dan freeze authority dicabut. Token-2022 di pump.fun biasanya hanya metadata pointer; ekstensi berbahaya (transfer fee, transfer hook, permanent delegate, default frozen, non-transferable) jarang, dan kalau ada itu red flag terpisah (sudah ada di rug.py F3).

Quote Jupiter "no route" di kurva muda hampir selalu karena **SOL di kurva tipis**, bukan pintu jual dikunci. Modul rug sudah mencoba ukuran 1% sebelum menuduh honeypot.

**Honeypot / pintu jual macet relevan setelah lulus** (PumpSwap, Raydium, Meteora, Token-2022 di luar pump.fun): freeze authority hidup, transfer hook, sell tax, atau LP ditarik. Bevan sendiri bilang pernah kena honeypot dan lebih aman di pump.fun/bonk daripada koin Raydium "biasa".

Karena itu:

- Anti-honeypot sebagai **hard filter live / forward**: rug F1 mint, F2 freeze, F3 T22 berbahaya, F10 quote jual Jupiter (plus liq_watch untuk LP pull setelah entry). Ini wajib di paper bot, tapi **tidak bisa di-backtest di rec bonding curve** (field-nya tidak terekam; di kurva hasilnya hampir selalu lolos).
- Di backtest kurva: jangan klaim "anti-honeypot lulus OOS". Yang bisa diuji di rec adalah proksi rug yang ada: dev_pct, dev_sold, bundle, top10, creator_prev_rugs, growth sudah +100%, liq_sol.
- Di backtest lulusan (lulus-data / GT): anti-honeypot tetap terbatas (tidak ada quote Jupiter historis). Pakai LP/liq terekam saat deteksi saja, jangan rugcheck hari ini.

---

## 6. Modul kandidat (dikunci sebelum tes)

Ambang yang sudah gagal OOS (checklist Bevan 60 dtk, snipe dev langganan, graduation 50–98% grid zostaff, copy wallet min5 WR≥50% yang lulus = null, gabungan Bom+mom120) **tidak dituning lagi**. Modul di bawah ini beda jendela, beda mode entry, atau hard filter defensif.

### G1 — Hard anti-rug / anti-honeypot (agent: rug) — wajib di v2 paper, bukan pencari edge

Live/forward (bukan parameter yang diutak-atik di A):

- FAIL jika mint authority ≠ null, freeze ≠ null, T22 berbahaya, rugcheck danger, LP locked < 80% (hanya setelah ada pool), top10 > 30% (varian laporan: juga 35% seperti nfp/Bevan — ini boleh diuji di rec karena top10 ada di snapshot).
- FAIL honeypot: tidak ada rute jual Jupiter (ukuran penuh lalu 1%) atau round-trip < 0,85x — **forward only**.
- Bonding curve: lewati cek LP; jangan flag honeypot hanya karena quote 0,1 SOL gagal.

Backtestable di rec: top10 ≤ 30% atau ≤ 35%; dev_pct ≤ 5% (nfp) atau ≤ 10%; dev_sold_any; creator_prev_rugs ≥ 1 atau ≥ 2; bundle di atas ambang. Ini tumpang tindih dengan Bevan yang sudah gagal kalau keputusan di umur 60–120 dtk — jadi **hanya diuji ulang sebagai gerbang defensif** di mode entry baru (G3), bukan sebagai strategi berdiri sendiri.

### G2 — Latar: bundle, fresh, dev jual (agent: latar)

Dari nfp + Bevan + x1:

- Tolak bundle (chip x1: 7% masih lulus, 38% dev ditolak — bundle % exact tidak ada skala di nfp, hanya "Bundled buys").
- Tolak fresh-wallet-dominated (di rec: proksi = banyak pembeli unik vs inflow, atau buyer_rate tinggi dengan holders rendah — **tulis rumus proksi di skrip sebelum jalan**, karena % fresh wallet GMGN tidak terekam).
- Tolak jika dev sudah jual (nfp 40%; rec punya `dev_sold_any` biner, bukan 40% — pakai dev_sold_any dan/atau penurunan dev_pct antar snapshot, tanpa mengarang 40% kalau tidak ada angka).

Backtestable sebagian (proksi). Funding-hop linked wallets: **tidak ada di rec → needs new recorder / forward only**.

### G3 — Mode entry "koin lama masih di bawah mcap X" (agent: data) — ide user

Bukan hanya beli saat listing. Keputusan di umur T jika mcap (USD) masih di pita M.

- T (umur): 2, 5, 10 menit = snapshot 120, 300, 600 dtk → **BACKTESTABLE di rec**.
- T = 30 menit: harga/candle ada (end s/d 1800 dtk), tapi fitur holder terakhir di 10 menit (boleh dipakai kausal sebagai "fitur umur 10 menit untuk keputusan 30 menit", harus dilabeli stale). **Backtestable terbatas**.
- T = 60 menit dan 1–3 hari (Bevan swing): **tidak ada di rec. Butuh recorder baru atau data lulusan+GT. Forward test / data lulusan saja.**
- Pita mcap USD: <$10k, $10–30k, $30–60k, $60–100k. Konversi wajib: `mcap_usd = mcap_sol * SOLUSD`. SOLUSD pakai harga saat t0 jika ada, kalau tidak tulis asumsi tetap (mis. $86 seperti 10 Nov) di log sebelum hasil.
- Catatan: $60–100k sudah di sekitar/lepas kelulusan (~$69k tipikal). Di rec murni kurva, pita ini mungkin hampir kosong.

Syarat tambahan yang diuji di G3 (pilih di A, sekali di B; bukan semua kali semua):

- belum +100% dari m0 (nfp "already +100% 1h"; di 10 menit pakai growth snapshot).
- liq_usd vs pita (nfp $25k hampir tidak relevan di kurva; tetap diuji di lulusan).
- hard G1 yang backtestable.
- bukan already dumped (drawdown di atas ambang, kandidat 40%/50%).

Ini **satu keluarga ide**, bukan 4×5×banyak exit tanpa koreksi. Picker: ranking di A, maks 5 finalis masuk B.

### G4 — Jangan kejar yang sudah terbang (agent: data / Guard pra-entry)

- Skip jika growth ≥ 2x sejak m0 pada jendela 1 jam (di rec: growth di snapshot keputusan).
- Pita harga setelah vote (10/15/25/tanpa pita) — sudah dijanjikan user, tetap diuji.

Backtestable di rec (growth) dan di lulusan (price change 1j kalau ada).

### G5 — Graduation / kurva tinggi (agent: data)

Zostaff 92% dan grid 50–98% sudah gagal / n kurang. **Tidak diuji ulang sebagai keluarga besar.** Tidak masuk picker kecuali sebagai satu baris kontrol "kurva ≥ 92%, exit 2x/−50%/120 dtk" di data besar GitHub, tanpa perluasan grid, hanya untuk laporan pembanding.

### G6 — Whale copy / konfirmasi (agent: whale)

Daftar terkunci: `riset/wallet-whale-x-2026-11-10.csv` (99 alamat publik). Varian (dikunci):

- **Confirm:** entry hanya jika ≥1 (varian ≥2, ≥3) wallet di daftar sudah beli koin itu sebelum umur keputusan, di tape yang kausal (rec prefix 10 huruf, atau whale_data lengkap untuk pasca-lulus).
- **Copy:** entry saat beli pertama yang terlihat, plus jeda 3–8 / 1 / 0,4 dtk, plus G1 defensif.
- Buku WR: nfp "wallet WR <55%" — WR dihitung hanya dari trade **sebelum** split A, lalu dibekukan (seperti whale_wallets Rock). Jangan pakai WR 24 jam yang dihitung setelah hasil.

Backtestable jika alamat (atau prefix unik) muncul di tape. Di rec lokal 65 menit: hanya 6/99 prefix yang muncul. Di tape PumpSwap 8–10 Nov: 60/99 alamat lengkap muncul. Tes resmi butuh cache GitHub (prefix 10 huruf; catat risiko tabrakan prefix). Copy KOL/7BNaxx sudah kalah OOS — daftar ini boleh diuji sebagai konfirmasi, bukan diulang sebagai copy buta.

### G7 — Guard exit (bukan voter)

Kandidat yang diuji (sudah umum, harus praregistrasi tetap): SL −8% (nfp), −30% (Bevan), −50% (zostaff); TP 1.5x / 2x; time-stop 120 dtk / 10 menit / 30 menit; keluar saat dev_sold_any setelah entry. Stop candle ×0,72. Jangan trailing "sempurna".

---

## 7. Yang tidak diuji / bukan modul

- Klaim profit nfp, ISSA TERMINAL, IG aitechdaily, reactorworld, onchainlyfe, zostaff.
- CU price 0 / "tanpa program kustom" (tidak ada di data).
- Database 4–5k wallet pribadi Bevan (tidak publik).
- Link referral, Telegram, FOMO/GMGN Connect Wallet.
- Mengutak-atik Bom v1 yang terkunci, mom120 yang sudah diperbaiki, atau forward test terkunci.

---

## 8. Urutan kerja setelah spek ini (belum dieksekusi)

1. Hash SHA256 file ini dan catat di `spec-filter-baru-2026-11-10.sha256`.
2. Tulis skrip di branch baru (bukan main/strat100k) hanya setelah user/Bom menyuruh jalan. Jangan dispatch dari spek ini.
3. Restore cache `memescan-data-*`, pakai A+B saja, null 20×, Bonferroni, sim $200 8/10% max1/max5.
4. Konfirmasi hanya di data t0 > 10 Nov 07:17 UTC jika cache lebih baru ada.
5. Laporan Indonesia, baris pertama LAYAK / TIDAK LAYAK. Kalau ada finalis, baru rancang kuncinya ke paper forward Bom v2. Kalau tidak, v1 dan mom120 tetap pembanding.

---

## 9. Ringkas backtestability per ide

| Ide | Sumber | Agent | Status data |
|---|---|---|---|
| Dev >5% / top10 >30–35% / bundle / dev sold / prev rugs | nfp, Bevan, x1, X checklist | rug/latar | BACKTESTABLE di rec (sudah pernah gagal di jendela 60–120 dtk; uji ulang hanya sebagai gerbang di G3) |
| Liq < $25k, LP locked | nfp, X, Bevan | rug/data | Kurva: tidak applicable / hampir selalu gagal liq. Pasca-lulus: BACKTESTABLE jika liq terekam saat sinyal; LP lock historis sering tidak ada |
| +100% 1h / pita harga | nfp, user, reactorworld | data/Guard | BACKTESTABLE (growth snapshot / candle) |
| Fresh wallet % / funding hop | nfp, Bevan | latar | Proksi parsial di rec; funding hop = needs recorder baru (forward) |
| Wallet WR <55% / copy 512 wallet | nfp | whale | BACKTESTABLE jika wallet ada di tape; rec cuma prefix 10 huruf |
| Mcap pita × umur 2/5/10 menit | user + nfp/x1 MC rendah | data | BACKTESTABLE di rec (konversi SOLUSD) |
| Umur 30 menit + mcap | user | data | BACKTESTABLE terbatas (fitur holder stale 10 menit) |
| Umur 60 menit / 1–3 hari masih hidup | user, Bevan swing | data | NEEDS NEW RECORDER atau data lulusan+GT; forward |
| Snipe dev langganan, graduation 92%, copy WR≥50% grid | Bevan, zostaff | data/whale | Sudah diuji, gagal / = null; jangan grid ulang |
| Anti-honeypot (quote jual, freeze, T22 hook) | user, Bevan, X, rug.py | rug | Kurva: hampir tidak applicable. Live/forward wajib. Backtest historis: tidak ada quote; authority tidak terekam di rec |
| Narasi X / KOL endorse | Bevan, Bottle | narasi | Tidak backtestable jujur di data lama; skenario N-skip / N-yes saja |
| Follow @DumbCrayonEater / FOMO | reactorworld | — | Tidak applicable (bukan alamat Solana; aplikasi beli) |

