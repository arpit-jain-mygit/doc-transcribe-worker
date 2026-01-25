## **Doc-Transcribe Worker - Dead-Letter Job Schema**

This document defines the schema for **failed jobs** that are moved to the **Dead-Letter Queue (DLQ)** after all retry attempts are exhausted or a non-recoverable error occurs.

The dead-letter queue ensures **no job failure is lost** and allows:

- debugging
- alerting
- replaying failed jobs
- surfacing meaningful errors to UI/API

## **1\. When a Job Enters the Dead-Letter Queue**

A job MUST be sent to the dead-letter queue if **any** of the following occur:

- maximum retry attempts are exhausted
- schema validation fails
- input file is missing or unreadable
- Gemini / OCR returns repeated fatal errors
- unsupported job type or input type
- non-recoverable runtime exception

## **2\. Dead-Letter Job Schema**

{  
"job_id": "string (required)",  
"job_type": "OCR | TRANSCRIPTION",  
"input_type": "PDF | VIDEO | AUDIO",  
<br/>"payload": {  
"...": "original job payload"  
},  
<br/>"status": "FAILED",  
<br/>"error": "string (human-readable failure reason)",  
"error_type": "VALIDATION | IO | MODEL | SYSTEM",  
<br/>"attempts": 3,  
"max_attempts": 3,  
<br/>"failed_at": "ISO-8601 timestamp",  
<br/>"worker_id": "string (optional)",  
"schema_version": "v1"  
}  

## **3\. Field Definitions**

| **Field** | **Required** | **Description** |
| --- | --- | --- |
| job_id | ✅   | Original job identifier |
| job_type | ✅   | Job category |
| input_type | ✅   | Input data type |
| payload | ✅   | Full original job payload |
| status | ✅   | Always FAILED |
| error | ✅   | Final error message |
| error_type | ❌   | High-level error category |
| attempts | ✅   | Number of attempts made |
| max_attempts | ❌   | Configured retry limit |
| failed_at | ✅   | Failure timestamp |
| worker_id | ❌   | Worker instance identifier |
| schema_version | ❌   | Schema version (default v1) |

## **4\. Example Dead-Letter Jobs**

### **4.1 OCR Failure - Missing File**

{  
"job_id": "ocr-009",  
"job_type": "OCR",  
"input_type": "PDF",  
"payload": {  
"local_path": "samples/missing.pdf"  
},  
"status": "FAILED",  
"error": "File not found: samples/missing.pdf",  
"error_type": "IO",  
"attempts": 3,  
"max_attempts": 3,  
"failed_at": "2026-01-25T11:02:14Z",  
"schema_version": "v1"  
}  

### **4.2 Transcription Failure - Unsupported URL**

{  
"job_id": "tr-017",  
"job_type": "TRANSCRIPTION",  
"input_type": "VIDEO",  
"payload": {  
"url": "<https://example.com/private>"  
},  
"status": "FAILED",  
"error": "Unable to download audio",  
"error_type": "IO",  
"attempts": 2,  
"max_attempts": 2,  
"failed_at": "2026-01-25T11:10:47Z",  
"schema_version": "v1"  
}  

## **5\. Dead-Letter Queue Naming**

Recommended Redis queue name:

doc_jobs_dead  

## **6\. Replay Strategy (Future)**

A dead-letter job **may be replayed** by:

- fixing the root cause (file, URL, config)
- re-enqueueing the payload as a new job
- generating a new job_id

Dead-letter entries **must never** be auto-replayed.

## **7\. Compatibility & Versioning**

- Dead-letter schema version: **v1**
- New fields may be added
- Existing fields must not be removed or renamed
- Breaking changes require a new schema version

## **8\. Summary**

- Dead-letter jobs preserve **failure truth**
- Every failed job is inspectable
- No silent loss of work
- Enables operational confidence

This schema is the **last line of defense** in the system.