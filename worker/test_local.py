# User value: This file helps users get reliable OCR/transcription results with clear processing behavior.
# -*- coding: utf-8 -*-
"""
Local test runner for doc-transcribe-worker
NO Redis. NO API. Direct dispatcher execution.
"""

import time
import traceback
from pprint import pprint

from worker.dispatcher import dispatch


# User value: supports banner so the OCR/transcription journey stays clear and reliable.
def banner(title: str):
    print("\n" + "=" * 80)
    print(f"🧪 {title}")
    print("=" * 80 + "\n", flush=True)


# User value: supports log so the OCR/transcription journey stays clear and reliable.
def log(msg: str):
    print(f"▶️  {msg}", flush=True)


# User value: supports log_ok so the OCR/transcription journey stays clear and reliable.
def log_ok(msg: str):
    print(f"✅ {msg}", flush=True)


# User value: supports log_err so the OCR/transcription journey stays clear and reliable.
def log_err(msg: str):
    print(f"❌ {msg}", flush=True)


# ---------------------------------------------------------
# OCR TEST
# ---------------------------------------------------------
# User value: supports test_pdf_ocr so the OCR/transcription journey stays clear and reliable.
def test_pdf_ocr():
    banner("PDF OCR TEST (Local, No Redis)")

    job = {
        "job_id": "local-test-ocr-001",
        "job_type": "OCR",
        "input_type": "PDF",
        "local_path": "samples/sample.pdf",
    }

    log("Dispatching OCR job")
    pprint(job)

    start = time.perf_counter()

    try:
        result = dispatch(job)
        duration = time.perf_counter() - start

        log_ok("OCR job completed successfully")
        log(f"Execution time: {duration:.2f}s")

        print("\n📄 OCR RESULT:")
        pprint(result)

    except Exception as e:
        log_err("OCR job failed")
        traceback.print_exc()


# ---------------------------------------------------------
# TRANSCRIPTION TEST
# ---------------------------------------------------------
# User value: supports test_video_transcription so the OCR/transcription journey stays clear and reliable.
def test_video_transcription():
    banner("VIDEO TRANSCRIPTION TEST (Local, No Redis)")

    job = {
        "job_id": "local-test-transcribe-001",
        "job_type": "TRANSCRIPTION",
        "input_type": "AUDIO",
        "local_path": "samples/sample.mp3",
    }

    log("Dispatching transcription job")
    pprint(job)

    start = time.perf_counter()

    try:
        result = dispatch(job)
        duration = time.perf_counter() - start

        log_ok("Transcription job completed successfully")
        log(f"Execution time: {duration:.2f}s")

        print("\n📝 TRANSCRIPTION RESULT:")
        pprint(result)

    except Exception as e:
        log_err("Transcription job failed")
        traceback.print_exc()


# ---------------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------------
if __name__ == "__main__":
    banner("DOC-TRANSCRIBE WORKER — LOCAL TEST MODE")

    print(
        "ℹ️  This test bypasses Redis and API.\n"
        "ℹ️  Pipelines are executed directly via dispatcher.\n",
        flush=True,
    )

    # Uncomment what you want to test
    #test_pdf_ocr()
    test_video_transcription()

    print("\n🎉 Local test run finished\n", flush=True)
