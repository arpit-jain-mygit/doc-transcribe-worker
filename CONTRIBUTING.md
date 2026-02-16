# Contributing (Worker)

## Canonical contract
- Job/status contract reference: `JOB_STATUS_CONTRACT.md`

## Architecture rule
Follow `/ARCHITECTURE.md` boundaries before changing queue, dispatcher, OCR, or transcription code.

## Mandatory checklist for every backlog item fix
- Mention backlog ID (`PRS-xxx`).
- Add/adjust logs for start, stage updates, success/failure.
- Map exceptions to explicit failure classes.
- Ensure status update writes remain consistent.
- Add test notes (sample input + expected status path).

## Logging minimum
- Include: `job_id`, `request_id` (if available), `stage`, `duration_sec`, `error_code`.
- Avoid secrets/private data in logs.

## Review checklist
- No queue-lifecycle logic in executor modules.
- No silent exception swallowing.
- No status transition without explicit stage/status write.
