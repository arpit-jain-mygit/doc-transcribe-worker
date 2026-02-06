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


def process_youtube_job(job_id: str, job: dict):
    """
    job = {
      "source": "youtube",
      "url": "...",
      "type": "TRANSCRIPTION"
    }
    """

    urls = expand_urls([job["url"]])
    total = len(urls)

    results = []

    for idx, url in enumerate(urls, start=1):
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

            result = run_transcription(job_id, child_job, finalize=False)
            results.append(result)

    safe_hset(
        f"job_status:{job_id}",
        {
            "status": "COMPLETED",
            "stage": "Completed",
            "progress": 100,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    return results

