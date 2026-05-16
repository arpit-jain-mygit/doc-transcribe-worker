# Worker Architecture (`doc-transcribe-worker`)

## Purpose
Keep queue orchestration, execution logic, and adapters separated for easier reliability and debugging.

## Layers and dependency direction
Allowed direction:
- `worker_loop` (orchestrator runtime) -> dispatcher/orchestrator router -> executors (`worker/executors/*`)
- executors -> adapters (`worker/adapters/*`, `worker/utils/*`, model client wrappers)
- domain/shared types/errors can be used by all layers

Disallowed direction:
- executor owning queue polling lifecycle
- adapter owning orchestration decisions

## Canonical contract
- Job status contract reference: `JOB_STATUS_CONTRACT.md`

## Current modules (as-is)
- `worker/worker_loop.py`: queue poll and lifecycle updates
- `worker/dispatcher.py`, `worker/orchestrator/router.py`: routing/orchestration to executors
- `worker/executors/ocr_executor.py`, `worker/executors/transcription_executor.py`: executor boundaries
- `worker/ocr.py`, `worker/transcribe.py`: core execution engines used by executors
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
