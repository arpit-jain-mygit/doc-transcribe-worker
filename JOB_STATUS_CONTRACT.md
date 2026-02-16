# Worker Job/Status Contract Reference

Canonical source of truth:
- API repo: `/Users/arpitjain/PycharmProjects/doc-transcribe-api/JOB_STATUS_CONTRACT.md`

Contract version expected by worker:
- `2026-02-16-prs-005`

Worker contract responsibilities:
- Read `job_type` from payload and route execution (`OCR` or `TRANSCRIPTION`).
- Update canonical lifecycle fields during processing:
  - `request_id`
  - `status`
  - `stage`
  - `progress`
  - `updated_at`
- Write canonical outcome fields:
  - `duration_sec`
  - `output_path`
  - `output_filename`
  - `total_pages` (OCR only)
  - `error` on failures

Rules:
- Keep status values inside canonical enum set only.
- Do not invent repo-specific alternate status names.
- Any contract field change must originate in API canonical contract and then be consumed here.
