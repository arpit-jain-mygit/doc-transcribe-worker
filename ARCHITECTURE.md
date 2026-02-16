# Worker Architecture (`doc-transcribe-worker`)

## Purpose
Keep queue orchestration, execution logic, and adapters separated for easier reliability and debugging.

## Layers and dependency direction
Allowed direction:
- `worker_loop` (orchestrator) -> dispatcher -> executors (`ocr`, `transcribe`)
- executors -> adapters (`redis`, `gcs`, model client wrappers)
- domain/shared types/errors can be used by all layers

Disallowed direction:
- executor owning queue polling lifecycle
- adapter owning orchestration decisions

## Current modules (as-is)
- `worker/worker_loop.py`: queue poll and lifecycle updates
- `worker/dispatcher.py`, `worker/jobs/processor.py`: routing to OCR/transcription
- `worker/ocr.py`, `worker/transcribe.py`: core execution
- `worker/cancel.py`: cancellation helpers

## Target boundary (incremental)
- Keep queue lifecycle in orchestrator only
- Keep OCR/transcription pure execution modules
- Keep external clients behind adapter-style modules

## Logging requirements for every backlog item fix
- For each job, log:
  - receive/start (`job_id`, `request_id` if present)
  - stage transitions
  - completion/failure with `duration_sec` and `error_code`
- Never log secrets or raw credentials.

## PR placement checklist
- Are orchestration decisions isolated from execution modules?
- Are transient vs permanent failures explicitly handled?
- Are logs added for new stages and error paths?
