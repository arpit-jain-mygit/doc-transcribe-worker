# yt_utils.py
import yt_dlp
import os
import re
import unicodedata


def sanitize_filename(name, max_len=180):
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    return name[:max_len]

def expand_urls(urls):
    expanded = []
    with yt_dlp.YoutubeDL({
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
    }) as ydl:
        for url in urls:
            info = ydl.extract_info(url, download=False)
            if info.get("_type") == "playlist":
                for e in info["entries"]:
                    expanded.append(f"https://www.youtube.com/watch?v={e['id']}")
            else:
                expanded.append(url)
    return expanded
