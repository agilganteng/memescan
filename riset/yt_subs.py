# Ambil subtitle (otomatis/manual) semua video YouTube yang memuat Bevan Pramudito, plus video TikTok pribadinya.
# Hasil: riset/yt/<id>.txt (teks dengan penanda menit) dan riset/yt/index.tsv
import json, os, re, sys, time, glob
import yt_dlp

OUT = 'riset/yt'
os.makedirs(OUT, exist_ok=True)
SOURCES = [l.strip() for l in open('riset/yt-request.txt') if l.strip() and not l.startswith('#')]
KEY = re.compile(r'bevan', re.I)

def flat(url):
    o = {'extract_flat': True, 'quiet': True, 'ignoreerrors': True, 'playlistend': 400}
    with yt_dlp.YoutubeDL(o) as y:
        info = y.extract_info(url, download=False) or {}
    return [e for e in (info.get('entries') or []) if e]

cands = {}
for src in SOURCES:
    must = not src.startswith('ALL ')
    url = src[4:] if src.startswith('ALL ') else src
    try:
        es = flat(url)
    except Exception as ex:
        print('ERR flat', url, ex); continue
    n = 0
    for e in es:
        vid = e.get('id'); t = (e.get('title') or '') + ' ' + (e.get('description') or '') + ' ' + (e.get('channel') or e.get('uploader') or '')
        if not vid: continue
        if must and not KEY.search(t): continue
        u = e.get('url') or e.get('webpage_url') or vid
        if 'tiktok' in url and not u.startswith('http'): u = 'https://www.tiktok.com/@x/video/' + vid
        if 'youtube' in url or 'ytsearch' in url: u = 'https://www.youtube.com/watch?v=' + vid
        cands[vid] = u; n += 1
    print(f'{src}: {len(es)} entri, {n} dipakai', flush=True)

print('total kandidat', len(cands), flush=True)

def vtt_to_text(path):
    lines = open(path, encoding='utf-8', errors='ignore').read().splitlines()
    out, last_t, last_line, mark = [], None, '', -999
    for ln in lines:
        m = re.match(r'(\d+):(\d+):(\d+)\.\d+ -->', ln) or re.match(r'(\d+):(\d+)\.\d+ -->', ln)
        if m:
            g = [int(x) for x in m.groups()]
            sec = g[0]*3600+g[1]*60+g[2] if len(g) == 3 else g[0]*60+g[1]
            if sec - mark >= 120:
                out.append(f'\n[{sec//60}m] '); mark = sec
            continue
        if not ln.strip() or ln.startswith(('WEBVTT', 'Kind:', 'Language:', 'NOTE')) or re.match(r'^\d+$', ln):
            continue
        s = re.sub(r'<[^>]+>', '', ln).strip()
        if s and s != last_line:
            out.append(s + ' '); last_line = s
    return ''.join(out)

rows = []
idx_path = f'{OUT}/index.tsv'
done = set()
if os.path.exists(idx_path):
    for l in open(idx_path, encoding='utf-8'):
        done.add(l.split('\t')[0])
for vid, u in cands.items():
    if vid in done and os.path.exists(f'{OUT}/{vid}.txt'):
        continue
    o = {'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True, 'subtitleslangs': ['id', 'id-orig', 'ind-ID', 'in', 'en', 'en-orig'],
         'subtitlesformat': 'vtt', 'outtmpl': f'{OUT}/raw/%(id)s.%(ext)s', 'quiet': True, 'ignoreerrors': True, 'sleep_interval_subtitles': 2}
    try:
        with yt_dlp.YoutubeDL(o) as y:
            info = y.extract_info(u, download=True) or {}
    except Exception as ex:
        print('ERR', vid, str(ex)[:200], flush=True); info = {}
    files = sorted(glob.glob(f'{OUT}/raw/{vid}*.vtt'))
    txt = vtt_to_text(files[0]) if files else 'NO_SUBS'
    head = f"TITLE: {info.get('title')}\nCHANNEL: {info.get('channel') or info.get('uploader')}\nDATE: {info.get('upload_date')}\nDURATION: {info.get('duration')}\nVIEWS: {info.get('view_count')}\nURL: {u}\nDESC: {(info.get('description') or '')[:600]}\n\n"
    open(f'{OUT}/{vid}.txt', 'w', encoding='utf-8').write(head + txt)
    with open(idx_path, 'a', encoding='utf-8') as f:
        f.write('\t'.join([vid, str(info.get('upload_date')), str(info.get('duration')), str(info.get('channel') or info.get('uploader')), (info.get('title') or '').replace('\t', ' '), str(len(txt)), u]) + '\n')
    print(vid, info.get('duration'), len(txt), (info.get('title') or '')[:60], flush=True)
    time.sleep(3)
