# Worker Guide (End-to-End)

This guide explains how to run and validate `doc-transcribe-worker` locally and in cloud/hybrid queue modes.

## 1. Repo Path

`/Users/arpitjain/PycharmProjects/doc-transcribe-worker`

## 2. What Worker Does

- Consumes queued jobs from Redis
- Dispatches by job type:
  - OCR -> `worker/ocr.py`
  - Transcription -> `worker/transcribe.py`
- Updates Redis job status/progress
- Uploads output to GCS
- Handles cancellation and DLQ fallback on failures

## 3. Queue Modes

Configured in `worker/worker_loop.py`:

- `QUEUE_MODE=single`
  - consume from `QUEUE_NAME`
  - failures to `DLQ_NAME`

- `QUEUE_MODE=both`
  - consume from both:
    - `LOCAL_QUEUE_NAME` (default `doc_jobs_local`)
    - `CLOUD_QUEUE_NAME` (default `doc_jobs`)
  - DLQ selected per source queue:
    - local -> `LOCAL_DLQ_NAME`
    - cloud -> `CLOUD_DLQ_NAME`

## 4. Required Environment Variables

Core:
- `REDIS_URL`
- `QUEUE_MODE` (`single` or `both`)
- `QUEUE_NAME` / `DLQ_NAME` (single mode)
- `CLOUD_QUEUE_NAME`, `CLOUD_DLQ_NAME` (both mode)
- `LOCAL_QUEUE_NAME`, `LOCAL_DLQ_NAME` (both mode)

Processing/GCP:
- `GCS_BUCKET_NAME`
- `GOOGLE_APPLICATION_CREDENTIALS_JSON` (base64 json credentials)
- Any model/provider env vars required by OCR/transcription modules

## 5. Install Dependencies

```bash
cd /Users/arpitjain/PycharmProjects/doc-transcribe-worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 6. Run Worker

```bash
cd /Users/arpitjain/PycharmProjects/doc-transcribe-worker
source .venv/bin/activate
python -m worker.worker_loop
```

Expected startup logs include:
- `Starting worker`
- `QUEUE_MODE=...`
- `QUEUE_TARGETS=[...]`
- `Redis connection successful`
- `Entering BRPOP wait targets=[...]`

## 7. Local End-to-End Flow

1. Start Redis.
2. Start Worker (`python -m worker.worker_loop`).
3. Start API (separate repo).
4. Start UI in local mode (`?api=local`).
5. Upload OCR or A/V file from UI.
6. Observe worker logs:
   - queue received
   - source classification
   - stage updates
   - completion / cancellation / DLQ behavior

## 8. Routing Logic

Worker routes to OCR when any of these are true:
- `source == "ocr"`
- `job_type == "OCR"`
- file extension looks like OCR input (`.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, `.tiff`)

Else it routes to transcription.

## 9. Cancellation Behavior

Worker checks cancel flags from Redis:
- `cancel_requested == 1`, or
- job status already `CANCELLED`

On cancellation, worker marks status `CANCELLED` and exits processing path.

## 10. DLQ Behavior

On processing error:
- marks job as `FAILED`
- pushes raw job payload into active DLQ

In `QUEUE_MODE=both`, DLQ depends on source queue:
- cloud queue -> `CLOUD_DLQ_NAME`
- local queue -> `LOCAL_DLQ_NAME`

## 11. Common Troubleshooting

### A) Worker shows only BRPOP timeouts

Cause:
- Wrong queue name or no jobs being pushed.

Fix:
- Verify API `QUEUE_NAME` and worker targets match.
- Check queue lengths with `redis-cli LLEN`.

### B) No cloud jobs while worker running local

Cause:
- worker listening only local queue.

Fix:
- Use `QUEUE_MODE=both` to consume both local and cloud queues.

### C) 429 / Resource exhausted from model provider

Cause:
- model quota/rate limits.

Fix:
- retry later, reduce concurrency/chunk pressure, or adjust quota/backoff strategy.

### D) GCS upload/download errors

Cause:
- missing/invalid credentials or bucket env vars.

Fix:
- verify `GCS_BUCKET_NAME` and `GOOGLE_APPLICATION_CREDENTIALS_JSON`.

## 12. Useful Commands

Run worker:
```bash
source .venv/bin/activate
python -m worker.worker_loop
```

Optional local tests:
```bash
./test_worker_local.sh
python -m worker.test_local
```

Inspect queues:
```bash
redis-cli -u "$REDIS_URL" LLEN doc_jobs
redis-cli -u "$REDIS_URL" LLEN doc_jobs_dead
redis-cli -u "$REDIS_URL" LLEN doc_jobs_local
redis-cli -u "$REDIS_URL" LLEN doc_jobs_local_dead
```
