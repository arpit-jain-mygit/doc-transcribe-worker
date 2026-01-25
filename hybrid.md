## **Hybrid Mode - Local Worker + Render API**

This is the **recommended mode** for:

- real usage
- remote job submission
- controlled costs
- local file access

## **Architecture**

Client / UI / curl  
↓  
Render API (FastAPI)  
↓  
Render Key Value (Redis)  
↓  
Local Worker (your machine)  

## **Prerequisites**

- Render API deployed and healthy
- Render Key Value (Redis) created
- External Redis access enabled (IP allow-list)
- Local worker machine reachable to Redis

## **Step 1 - Verify API is live**

curl <https://doc-transcribe-api.onrender.com/health>  

Expected:

{"status":"OK","redis":"connected"}  

## **Step 2 - Configure local worker to use Render Redis**

### **Copy External Redis URL from Render:**

[redis://:PASSWORD@external-xxxx.render.com:PORT](mailto:redis://:PASSWORD@external-xxxx.render.com:PORT)  

### **Export locally**

export [REDIS_URL="rediss://:PASSWORD@external-xxxx.render.com:PORT](mailto:REDIS_URL=)"  
export QUEUE_NAME="doc_jobs"  
export DLQ_NAME="doc_jobs_dead"  

Verify:

echo \$REDIS_URL  

## **Step 3 - Start local worker**

cd doc-transcribe-worker  
python -m worker.worker_loop  

You MUST see:

"redis_url": "rediss://..."  

and:

Waiting for job  

## **Step 4 - Submit OCR job via Render API**

curl -X POST <https://doc-transcribe-api.onrender.com/jobs/ocr> \\  
\-H "Content-Type: application/json" \\  
\-d '{"local_path":"samples/sample.pdf"}'  

Expected:

{"job_id":"ocr-...","status":"QUEUED"}  

Worker should wake up within seconds.

## **Step 5 - Submit transcription job**

curl -X POST <https://doc-transcribe-api.onrender.com/jobs/transcription> \\  
\-H "Content-Type: application/json" \\  
\-d '{"url":"<https://www.youtube.com/watch?v=VIDEO_ID"}>'  

## **Step 6 - Monitor job status**

curl <https://doc-transcribe-api.onrender.com/jobs/><job_id\>  

Status lifecycle:

QUEUED → PROCESSING → COMPLETED  

## **Important rules (Hybrid mode)**

- API uses **Internal Redis URL**
- Local worker uses **External Redis URL**
- Redis IP allow-list must include your machine
- Worker must be running for jobs to process
- Files referenced by local_path must exist locally

## **Common issues**

### **Worker stuck on localhost Redis**

Cause:

- REDIS_URL overridden by .env  
    Fix:
- remove REDIS_URL from .env
- restart worker

### **API accepts job but nothing runs**

Cause:

- worker not running
- wrong Redis URL  
    Fix:
- check worker startup log

## **When to move worker to Render**

Only after:

- file uploads added
- or object storage (S3 / GCS) introduced

Until then, **local worker is the correct design**.

## **Final note**

This setup gives you:

- cloud entry point
- durable queue
- local compute
- zero unnecessary cloud cost

It is **intentionally designed this way**.

## Delete Redis jobs

redis-cli DEL doc_jobs doc_jobs_dead
redis-cli KEYS "job_status:*" | xargs redis-cli DEL
redis-cli KEYS "job_attempts:*" | xargs redis-cli DEL

redis-cli -u "$REDIS_URL" DEL doc_jobs doc_jobs_dead
redis-cli -u "$REDIS_URL" KEYS "job_status:*" | xargs redis-cli -u "$REDIS_URL" DEL
redis-cli -u "$REDIS_URL" KEYS "job_attempts:*" | xargs redis-cli -u "$REDIS_URL" DEL