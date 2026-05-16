## **Run EVERYTHING locally (API + Redis + Worker)**

This mode is best for:

- rapid development
- debugging pipelines
- working fully offline
- avoiding any cloud dependency

## **Architecture**

Local Client (curl / UI)  
↓  
Local API (FastAPI)  
↓  
Local Redis  
↓  
Local Worker  

## **Prerequisites**

### **System dependencies**

brew install redis ffmpeg poppler  

Verify:

redis-server --version  
ffmpeg -version  
pdftoppm -v  

## **Repositories**

You should have:

doc-transcribe-api/  
doc-transcribe-worker/  

## **Step 1 - Start Redis locally**

redis-server  

Verify:

redis-cli ping  
\# PONG  

## **Step 2 - Run API locally**

cd doc-transcribe-api  
python -m venv .venv  
source .venv/bin/activate  
pip install -r requirements.txt  

### **Environment variables**

export REDIS_URL="redis://localhost:6379/0"  
export QUEUE_NAME="doc_jobs"  
export DLQ_NAME="doc_jobs_dead"  

### **Start API**

python -m uvicorn app:app --reload --port 8000  

Verify:

curl <http://localhost:8000/health>  

Expected:

{"status":"OK","redis":"connected"}  

## **Step 3 - Run worker locally**

cd doc-transcribe-worker  
python -m venv .venv  
source .venv/bin/activate  
pip install -r requirements.txt  

### **Worker env**

export REDIS_URL="redis://localhost:6379/0"  
export QUEUE_NAME="doc_jobs"  
export DLQ_NAME="doc_jobs_dead"  
<br/>export GEMINI_API_KEY="YOUR_KEY"  
export PROMPT_FILE="prompts/prompt.txt"  
export PROMPT_NAME="PRAVACHAN_PROMPT"  

### **Start worker**

python -m worker.worker_loop  

Expected:

Worker started  
Waiting for job  

## **Step 4 - Test OCR**

curl -X POST <http://localhost:8000/jobs/ocr> \\  
\-H "Content-Type: application/json" \\  
\-d '{"local_path":"samples/sample.pdf"}'  

Worker logs should immediately show OCR progress.

## **Step 5 - Test transcription**

curl -X POST <http://localhost:8000/jobs/transcription> \\  
\-H "Content-Type: application/json" \\  
\-d '{"local_path":"samples/sample.mp3"}'  

## **Step 6 - Check job status**

curl <http://localhost:8000/jobs/><job_id\>  

## **Reset Redis (dev only)**

redis-cli DEL doc_jobs doc_jobs_dead  
redis-cli KEYS "job_status:\*" | xargs redis-cli DEL  
redis-cli KEYS "job_attempts:\*" | xargs redis-cli DEL  

## **Notes**

- One worker = one job at a time
- OCR & transcription share the same queue
- CTRL+C is safe (jobs can be retried)
## Delete Redis jobs

redis-cli DEL doc_jobs doc_jobs_dead
redis-cli KEYS "job_status:*" | xargs redis-cli DEL
redis-cli KEYS "job_attempts:*" | xargs redis-cli DEL

redis-cli -u "$REDIS_URL" DEL doc_jobs doc_jobs_dead
redis-cli -u "$REDIS_URL" KEYS "job_status:*" | xargs redis-cli -u "$REDIS_URL" DEL
redis-cli -u "$REDIS_URL" KEYS "job_attempts:*" | xargs redis-cli -u "$REDIS_URL" DEL

## Verify Redis is clean
redis-cli LRANGE doc_jobs 0 -1
redis-cli LRANGE doc_jobs_dead 0 -1

(empty array)
