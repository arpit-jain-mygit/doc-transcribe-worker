from youtube.yt_utils import expand_urls, sanitize_filename
from storage import upload_text
from progress import update_progress

def process_youtube_job(job, gemini_client, prompt):
    urls = expand_urls([job.input_url])
    total = len(urls)

    outputs = []

    for idx, url in enumerate(urls, start=1):
        update_progress(
            job,
            stage=f"Processing video {idx}/{total}",
            progress=int((idx - 1) / total * 100)
        )

        mp3, title = download_youtube_audio(url)
        text = transcribe_audio(mp3, gemini_client, prompt)

        filename = sanitize_filename(title) + ".txt"
        gcs_path = f"youtube/{job.id}/{filename}"

        download_url = upload_text(gcs_path, text)
        outputs.append(download_url)

    return outputs
