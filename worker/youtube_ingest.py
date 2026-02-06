# worker/youtube_ingest.py

import tempfile
from worker.youtube.yt_utils import expand_urls
from worker.utils.gcs import upload_file
from worker.transcribe import run_transcription, update
import yt_dlp
import os
from datetime import datetime
from worker.transcribe import safe_hset


def download_audio(url: str, out_dir: str) -> str:
    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),

        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,

        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],

        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    return os.path.join(out_dir, f"{info['id']}.mp3"), info


from worker.utils.gcs import append_log

def process_youtube_job(job_id: str, job: dict):
    urls = expand_urls([job["url"]])
    total = len(urls)
    results = []

    for idx, url in enumerate(urls, start=1):
        try:
            update(
                job_id,
                stage=f"Downloading YouTube audio {idx}/{total}",
                progress=int((idx - 1) / total * 30),
            )

            with tempfile.TemporaryDirectory() as tmp:
                mp3_path, info = download_audio(url, tmp)

                upload = upload_file(
                    local_path=mp3_path,
                    destination_path=f"youtube/{job_id}/{idx}.mp3",
                )

                child_job = {
                    "input_gcs_uri": upload["gcs_uri"],
                    "source": "youtube",
                    "video_url": url,
                    "video_title": info.get("title"),
                }

                update(
                    job_id,
                    stage=f"Transcribing video {idx}/{total}",
                    progress=30 + int((idx / total) * 60),
                )

                result = run_transcription(job_id, child_job)
                results.append(result)

        except Exception as e:
            # 🔴 THIS WAS MISSING
            err = str(e)
            append_log(job_id, f"YouTube download failed: {err}")

            safe_hset(
                f"job_status:{job_id}",
                {
                    "status": "FAILED",
                    "stage": "YouTube download failed",
                    "progress": 100,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )

            update(
                job_id,
                stage="YouTube download failed",
                progress=100,
                status="FAILED",
            )

            raise  # Let worker_loop DLQ it

    return results
