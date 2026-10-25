"""Baca satu postingan X lewat API publik fxtwitter/vxtwitter (tanpa login), simpan teks + media
ke riset/tweet/<id>/ supaya bisa dibaca dari luar GitHub Actions. Pakai: python3 riset/baca_tweet.py <user> <id>"""
import json
import os
import subprocess
import sys
import urllib.request

user, tid = sys.argv[1], sys.argv[2]
UA = {"User-Agent": "Mozilla/5.0 memescan-riset"}
out = os.path.join("riset", "tweet", tid)
os.makedirs(out, exist_ok=True)


def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
        return r.read()


data = None
for u in [f"https://api.fxtwitter.com/{user}/status/{tid}", f"https://api.vxtwitter.com/{user}/status/{tid}"]:
    try:
        data = json.loads(get(u))
        print("OK", u)
        break
    except Exception as e:  # noqa: BLE001
        print("gagal", u, type(e).__name__, e)
if data is None:
    sys.exit(1)
json.dump(data, open(os.path.join(out, "tweet.json"), "w"), indent=1, ensure_ascii=False)
t = data.get("tweet", data)
print("teks:", t.get("text"))
urls = []
media = t.get("media") or {}
for m in (media.get("all") or media.get("photos") or []) if isinstance(media, dict) else []:
    urls.append((m.get("type"), m.get("url")))
for m in t.get("media_extended") or []:
    urls.append((m.get("type"), m.get("url")))
q = t.get("quote") or {}
for m in ((q.get("media") or {}).get("all") or []):
    urls.append(("quote-" + str(m.get("type")), m.get("url")))
for i, (kind, u) in enumerate(urls):
    if not u:
        continue
    ext = ".mp4" if "video" in str(kind) or "gif" in str(kind) or u.split("?")[0].endswith(".mp4") else ".jpg"
    fn = os.path.join(out, f"media{i}{ext}")
    open(fn, "wb").write(get(u))
    print("media", kind, u, os.path.getsize(fn))
    if ext == ".mp4":
        os.makedirs(os.path.join(out, f"frames{i}"), exist_ok=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", fn, "-vf", "fps=1/2,scale=540:-2",
                        os.path.join(out, f"frames{i}", "f_%03d.jpg")], check=False)
        os.remove(fn)
