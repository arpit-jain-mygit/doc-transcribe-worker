#!/usr/bin/env bash
set -e

echo "=== Local Worker Test Script ==="

# -------- CONFIG --------
export REDIS_URL=redis://localhost:6379/0
QUEUE=doc_jobs
TXT_JOB_ID=local-test-transcribe-1
OCR_JOB_ID=local-test-ocr-1
PDF_PATH="/absolute/path/to/sample.pdf"   # <-- CHANGE THIS
# ------------------------

echo "1) Checking Redis..."
redis-cli ping

echo "2) Cleaning old test keys..."
redis-cli DEL job_status:$TXT_JOB_ID job_status:$OCR_JOB_ID >/dev/null || true

echo "3) Pushing TRANSCRIPTION job..."
redis-cli RPUSH $QUEUE '{
  "job_id": "'"$TXT_JOB_ID"'",
  "job_type": "TRANSCRIBE",
  "chunks": [
    {"text": "hello world"},
    {"text": "this is a test"},
    {"text": "worker pipeline ok"}
  ]
}'

echo "4) Waiting for transcription result..."
sleep 3
redis-cli HGETALL job_status:$TXT_JOB_ID

echo "5) Checking transcription output..."
if [ -f output_texts/$TXT_JOB_ID.txt ]; then
  cat output_texts/$TXT_JOB_ID.txt
else
  echo "transcription output not ready yet"
fi

echo "6) Pushing OCR job..."
redis-cli RPUSH $QUEUE '{
  "job_id": "'"$OCR_JOB_ID"'",
  "job_type": "OCR",
  "input_path": "'"$PDF_PATH"'"
}'

echo "7) Waiting for OCR result..."
sleep 5
redis-cli HGETALL job_status:$OCR_JOB_ID

echo "8) Checking OCR output..."
if [ -f output_texts/$OCR_JOB_ID.txt ]; then
  cat output_texts/$OCR_JOB_ID.txt
else
  echo "ocr output not ready yet"
fi

echo "=== DONE ==="
