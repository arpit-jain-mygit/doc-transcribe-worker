## **Doc-Transcribe Worker - Job & Result Schemas**

This document defines the **contract** between:

- UI
- API
- Redis queue
- Worker

Any job pushed to the queue **must** conform to these schemas.  
Any result returned by the worker **will** conform to the result schemas.

## **1\. Common Concepts**

### **Job**

A **job** represents a unit of work submitted to the worker.

### **Result**

A **result** represents the final outcome of a job after processing.

## **2\. Job Schema (Input)**

### **2.1 Common Job Fields (ALL jobs)**

{  
"job_id": "string (required, unique)",  
"job_type": "OCR | TRANSCRIPTION (required)",  
"input_type": "PDF | VIDEO | AUDIO (required)",  
"created_at": "ISO-8601 timestamp (optional)",  
"metadata": { "any": "optional contextual data" }  
}  

| **Field** | **Required** | **Description** |
| --- | --- | --- |
| job_id | ✅   | Unique identifier for the job |
| job_type | ✅   | Type of processing |
| input_type | ✅   | Input data category |
| created_at | ❌   | Job creation time |
| metadata | ❌   | Optional free-form metadata |

## **2.2 OCR Job Schema**

Used for **PDF → text (OCR)** processing.

{  
"job_id": "ocr-001",  
"job_type": "OCR",  
"input_type": "PDF",  
"local_path": "samples/sample.pdf"  
}  

### **Required Fields**

| **Field** | **Description** |
| --- | --- |
| local_path | Absolute or relative path to a local PDF file |

### **Notes**

- input_type must be PDF
- Worker assumes the file exists and is readable
- Remote URLs are **not** supported in v1

## **2.3 Transcription Job Schema**

Used for **audio/video → text transcription**.

{  
"job_id": "transcribe-001",  
"job_type": "TRANSCRIPTION",  
"input_type": "AUDIO",  
"local_path": "samples/sample.mp3"  
}  

### **Required Fields**

| **Field** | **Description** |
| --- | --- |
| local_path | Local path to audio/video file |

### **Notes**

- input_type may be VIDEO or AUDIO
- Worker reads local audio/video from local_path
- Remote URL ingestion is not supported

## **3\. Result Schema (Output)**

### **3.1 Common Result Fields (ALL jobs)**

{  
"job_id": "string",  
"status": "COMPLETED | FAILED",  
"duration_sec": 12.34,  
"output_path": "path/to/output.txt"  
}  

| **Field** | **Description** |
| --- | --- |
| job_id | Job identifier |
| status | Final job state |
| duration_sec | Total execution time |
| output_path | Local path to output file |

## **3.2 OCR Result Schema**

{  
"job_id": "ocr-001",  
"status": "COMPLETED",  
"output_path": "output_texts/sample.txt",  
"pages": 12,  
"duration_sec": 18.42  
}  

### **Additional Fields**

| **Field** | **Description** |
| --- | --- |
| pages | Number of pages processed |

## **3.3 Transcription Result Schema**

{  
"job_id": "transcribe-001",  
"status": "COMPLETED",  
"output_path": "transcripts/abc123_\_video_title.txt",  
"duration_sec": 24.71  
}  

## **4\. Failure Semantics**

If a job fails:

{  
"job_id": "ocr-002",  
"status": "FAILED",  
"error": "File not found",  
"duration_sec": 1.12  
}  

| **Field** | **Description** |
| --- | --- |
| error | Human-readable failure reason |

Failed jobs may be:

- retried
- sent to a dead-letter queue
- surfaced to UI/API

## **5\. Compatibility Rules**

- New fields may be **added**
- Existing fields must **not be renamed or removed**
- Breaking changes require a **new schema version**

## **6\. Versioning**

Current schema version: **v1**

Future versions may introduce:

- remote file support
- language hints
- speaker metadata
- output format options

## **7\. Summary**

- Jobs are **requests**
- Results are **responses**
- This file is the **contract**

Any component that produces or consumes jobs **must follow this schema**.