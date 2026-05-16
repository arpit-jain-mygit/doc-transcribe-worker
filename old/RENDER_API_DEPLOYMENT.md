## **Deploying doc-transcribe-api on Render (Step-by-Step)**

This document describes **exact steps** to deploy the FastAPI service (doc-transcribe-api) on Render.

## **Prerequisites**

Before starting, ensure:

- GitHub repo doc-transcribe-api is pushed
- You have a Render account
- A **Key Value (Redis)** instance is already created on Render
- You have copied the **Internal Redis URL**

## **Architecture Context**

Client / UI  
↓  
Render Web Service (FastAPI)  
↓  
Render Key Value (Redis)  
↓  
Render Background Worker  

## **Step 1 - Create Web Service**

- Go to **Render Dashboard**
- Click **\+ New**
- Select **Web Service**
- Choose **GitHub**
- Select repository: doc-transcribe-api
- Click **Continue**

## **Step 2 - Basic Configuration**

Fill the form as follows:

| **Field** | **Value** |
| --- | --- |
| Name | doc-transcribe-api |
| Region | Same as Redis |
| Branch | main |
| Runtime | Python |
| Plan | Free |

Leave other fields as default.

## **Step 3 - Build & Start Commands**

### **Build Command**

pip install -r requirements.txt  

### **Start Command (IMPORTANT)**

python -m uvicorn app:app --host 0.0.0.0 --port 10000  

⚠️ Notes:

- Render exposes **only port 10000**
- Do **not** use port 8000
- Always use python -m uvicorn

## **Step 4 - Environment Variables**

Scroll to **Environment Variables** and add the following:

### **Redis Configuration**

| **Key** | **Value** |
| --- | --- |
| REDIS_URL | &lt;Internal Redis URL&gt; |
| QUEUE_NAME | doc_jobs |
| DLQ_NAME | doc_jobs_dead |

⚠️ Use **Internal Redis URL**, not External.

## **Step 5 - Health Check**

Set **Health Check Path** to:

/health  

Render will only route traffic after this endpoint returns HTTP 200.

## **Step 6 - Create Service**

Click **Create Web Service**

Render will now:

- clone the repo
- install dependencies
- start the FastAPI app

## **Step 7 - Verify Deployment Logs**

Open the **Logs** tab.

Successful startup looks like:

Application startup complete.  
Uvicorn running on <http://0.0.0.0:10000>  

## **Step 8 - Test API Health**

Copy the public URL shown by Render, e.g.:

<https://doc-transcribe-api.onrender.com>  

Run:

curl <https://doc-transcribe-api.onrender.com/health>  

Expected response:

{  
"status": "OK",  
"redis": "connected"  
}  

## **Step 9 - Test Job Creation**

### **OCR Job**

curl -X POST <https://doc-transcribe-api.onrender.com/jobs/ocr> \\  
\-H "Content-Type: application/json" \\  
\-d '{"local_path":"samples/sample.pdf"}'  

Expected response:

{  
"job_id": "ocr-xxxxxxxx",  
"status": "QUEUED"  
}  

## **Step 10 - Validate End-to-End Flow**

Once API is deployed:

- Redis must be reachable
- Worker must be running
- Jobs should move from QUEUED → PROCESSING → COMPLETED

If jobs stay QUEUED, the worker is not running.

## **Common Mistakes to Avoid**

| **Mistake** | **Result** |
| --- | --- |
| Using External Redis URL | API cannot connect |
| Using port 8000 | Service never becomes healthy |
| Missing /health | Render keeps restarting |
| Worker not deployed | Jobs never execute |

## **Deployment Status Checklist**

- API service deployed
- /health returns OK
- Redis connected
- Job creation works
- Worker picks jobs

## **Next Steps**

After API deployment, proceed to:

- Deploy **Background Worker**
- Verify worker logs
- Run full end-to-end job

**Status:**  
✅ API is ready for production deployment on Render (internal or low-traffic use).