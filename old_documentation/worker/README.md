# Worker Module Map

Current structure:
- `worker_loop.py`: queue polling, lifecycle orchestration
- `dispatcher.py` + `jobs/processor.py`: route jobs to execution path
- `ocr.py`: OCR execution
- `transcribe.py`: A/V transcription execution
- `cancel.py`: cancellation checks and exception
- `utils/`: adapter helpers (e.g., gcs/redis-safe)

Boundary guidance:
- Orchestrator controls queue lifecycle and status transitions.
- Executors perform OCR/transcription only.
- Adapters handle external integrations and helper I/O.
