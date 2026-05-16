# doc-transcribe-worker
[![Worker CI](https://github.com/arpit-jain-mygit/doc-transcribe-worker/actions/workflows/ci.yml/badge.svg)](https://github.com/arpit-jain-mygit/doc-transcribe-worker/actions/workflows/ci.yml)

## Production env vars (Render/Worker)

Required:
- `REDIS_URL`
- `GCP_PROJECT_ID`
- `GCS_BUCKET_NAME`
- `PROMPT_FILE`
- `PROMPT_NAME`

Queue routing:
- `QUEUE_MODE=single|both|partitioned`
- For `single`: `QUEUE_NAME`, `DLQ_NAME`
- For `both`: `LOCAL_QUEUE_NAME`, `LOCAL_DLQ_NAME`, `CLOUD_QUEUE_NAME`, `CLOUD_DLQ_NAME`
- For `partitioned`: `OCR_QUEUE_NAME`, `OCR_DLQ_NAME`, `TRANSCRIPTION_QUEUE_NAME`, `TRANSCRIPTION_DLQ_NAME`

Concurrency and retry budgets:
- `WORKER_MAX_INFLIGHT_OCR`
- `WORKER_MAX_INFLIGHT_TRANSCRIPTION`
- `RETRY_BUDGET_TRANSIENT`
- `RETRY_BUDGET_MEDIA`
- `RETRY_BUDGET_DEFAULT`

Tuning:
- `TRANSCRIBE_CHUNK_DURATION_SEC`
- `OCR_DPI`
- `OCR_PAGE_BATCH_SIZE`
