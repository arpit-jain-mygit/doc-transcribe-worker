# Deployment Readiness Guide

This guide gets you fully ready for transcription processing across:
- GCP (project, IAM, bucket, credentials)
- Render (API + Worker)
- Vercel (UI)
- Local worker runtime (`.zshrc`)

Assumptions:
- Repos already exist: `doc-transcribe-ui`, `doc-transcribe-api`, `doc-transcribe-worker`
- You are on macOS (zsh shell)
- You have a new GCP free-tier account

---

## 0) Create a Fresh Free-Tier GCP Account (Important First Step)

Use this if your old account is locked to organization verification.

### 0.1 Create a new Gmail account
1. Open [Create Google Account](https://accounts.google.com/signup)
2. Create a fresh Gmail account dedicated for this project
3. Complete phone/email verification

Verification:
1. You can sign in successfully to Gmail with the new account

### 0.2 Start free-tier signup in Incognito mode
1. Open a new Incognito/Private browser window
2. Go to [Google Cloud Free Tier](https://cloud.google.com/free)
3. Click `Get started for free`
4. Sign in using the new Gmail account

Verification:
1. Free-tier onboarding page opens for the new account

### 0.3 Ensure billing profile type is Individual
1. During onboarding, choose `Individual` profile type (not Organization)
2. Add personal details and payment method
3. Complete verification prompts

Verification:
1. Free trial credits are visible in Cloud Console
2. No forced organization-document flow is shown

## 1) GCP Setup (Detailed + Verification After Each Step)

### 1.1 Install prerequisites on macOS

#### 1.1.1 Xcode Command Line Tools
```bash
xcode-select -p
```
If path is missing, install:
```bash
xcode-select --install
```
Verification:
```bash
xcode-select -p
```
Expected: a valid path like `/Library/Developer/CommandLineTools`.

#### 1.1.2 Homebrew
Check:
```bash
brew --version
```
If already installed and you want clean reinstall:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh)"
```
Install:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
Verification:
```bash
brew --version
```

#### 1.1.3 Google Cloud CLI (`gcloud`)
Check:
```bash
gcloud --version
```
If already installed and you want clean reinstall:
```bash
brew uninstall --cask google-cloud-sdk || true
rm -rf ~/google-cloud-sdk
```
Install:
```bash
brew install --cask google-cloud-sdk
```
Load shell config:
```bash
source ~/.zshrc
```
Initialize:
```bash
gcloud init
```
Verification:
```bash
gcloud --version
gcloud auth list
gcloud config list
```
Expected:
- active account is your GCP user
- a default project is set

#### 1.1.4 Verify exactly which GCP account `gcloud` is using
Print active account:
```bash
gcloud config get-value account
```

Print all authenticated accounts:
```bash
gcloud auth list
```

Print active project:
```bash
gcloud config get-value project
```

Optional deep check (identity email from access token):
```bash
gcloud auth print-access-token | awk '{print "token_generated"}'
```
Expected:
- `gcloud config get-value account` shows the account you intend to use
- In `gcloud auth list`, active account has `*`

#### 1.1.5 Install Poppler for OCR PDF processing (local worker prerequisite)
Install:
```bash
brew install poppler
```

Verification:
```bash
pdfinfo -v
```
Expected:
- `pdfinfo` command is available and prints version.

Troubleshooting:
- If worker logs show
  `PDFInfoNotInstalledError: Unable to get page count. Is poppler installed and in PATH?`
  then Poppler is missing or not on PATH.

---

### 1.2 Use the new account in `gcloud` config
Account reference in this guide:
- Email login: `sachin.arpit.gcp.may2026@gmail.com`
- Account label/handle: `sachin.arpit.gcp.may2026`

1. Login with the new account in CLI:
```bash
gcloud auth login sachin.arpit.gcp.may2026@gmail.com
```
2. Set active account:
```bash
gcloud config set account sachin.arpit.gcp.may2026@gmail.com
```
3. Confirm active account:
```bash
gcloud auth list
gcloud config get-value account
```
4. Continue to step `1.2.1` to create/select project.

Verification:
1. `gcloud config get-value account` returns `sachin.arpit.gcp.may2026@gmail.com`
2. In `gcloud auth list`, active account label should correspond to `sachin.arpit.gcp.may2026`

### 1.2.1 Create/select GCP project
1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Top bar project selector -> `New Project`
3. `Project name`: `my-project-transcription-16may` (or your final name)
4. `Organization` / `Parent resource` selection:
   - If this is personal free-tier setup, choose `No organization` (or parent resource shown as your user).
   - If your account shows an organization/folder dropdown and you do not intend org-managed setup, switch to personal/no-org scope.
   - If you must use org-managed setup, select the correct `Organization` and then correct `Folder` parent resource as instructed by your admin.
5. Optionally set custom `Project ID` now (recommended lowercase, e.g. `my-project-transcription-16may`)
6. Click `Create`
7. Select this project as active in top project selector

Verification:
- Console top bar shows selected project
- CLI:
```bash
gcloud projects list --format="table(projectId,name)"
```
Important:
- `gcloud config set project` expects **projectId**, not project display name.
- Project IDs are usually lowercase (example: `my-project-transcription-16may`).

Set active project using **projectId**:
```bash
gcloud config set project <your-project-id>
gcloud config get-value project
```
Expected: output is your lowercase project ID.

If project is not visible in CLI, confirm account + parent scope:
```bash
gcloud config get-value account
gcloud auth list
```
Expected: active account is the same account used in Console where project was created.

If you see ADC quota warning, align it:
```bash
gcloud auth application-default set-quota-project <your-project-id>
```
If you get:
`Cannot add the project ... because ADC does not have serviceusage.services.use`
then do:
```bash
gcloud auth application-default login
```
Sign in with `sachin.arpit.gcp.may2026@gmail.com`, then retry:
```bash
gcloud auth application-default set-quota-project <your-project-id>
```
If it still fails, continue setup and treat this as optional quota-alignment (not a hard blocker), then ask project admin to grant required permission (`serviceusage.services.use`).

---

### 1.3 Enable billing
1. Console -> `Billing`
2. Link your new project to billing account `sachin.arpit.gcp.may2026.free.billing.account` (free tier credits are okay)
3. If you see a red banner saying account must be verified, click `Verify account` and complete verification.
4. After verification, open `Billing` -> `Account management` -> `Projects linked` and confirm your project is listed.
5. If you see `No active billing accounts`:
   - Click `Manage billing accounts`
   - Create a new billing account named `sachin.arpit.gcp.may2026.free.billing.account` (Individual profile)
   - Complete payment profile and payment method verification
   - Return to project billing page and click `Link a billing account`
   - Select `sachin.arpit.gcp.may2026.free.billing.account`
6. If billing account status is `Closed`, reopen it using prepayment flow:
   - Open [Google Payments](https://payments.google.com)
   - Click the bell icon (top-right notifications)
   - Click `Pay now` for the billing account that must be reopened
   - Complete prepayment, then return to GCP Billing and verify status is `Open/Active`

Verification:
1. Red verification banner is no longer shown.
2. Billing page shows project linked.
3. CLI:
```bash
gcloud beta billing projects describe my-project-transcription-16may
```
Expected: `billingEnabled: true`

---

### 1.4 Enable required APIs
Enable APIs:
```bash
gcloud services enable storage.googleapis.com --project=my-project-transcription-16may
gcloud services enable aiplatform.googleapis.com --project=my-project-transcription-16may
```
If your worker uses specific generative APIs, enable those too per your model/provider.

Verification:
```bash
gcloud services list --enabled --project=my-project-transcription-16may | rg "storage|aiplatform"
```
Expected: both services appear.

---

### 1.5 Create GCS bucket
Pick globally unique bucket name, example:
- `my-project-transcription-16may-output`

Create:
```bash
gcloud storage buckets create gs://my-project-transcription-16may-output \
  --project=my-project-transcription-16may \
  --location=asia-south1 \
  --uniform-bucket-level-access
```

Verification:
```bash
gcloud storage buckets list --project=my-project-transcription-16may
gcloud storage ls gs://my-project-transcription-16may-output
```
Expected: bucket is listed and accessible.

---

### 1.6 Create service account for API/Worker
Create SA:
```bash
gcloud iam service-accounts create doc-transcribe-runtime \
  --project=my-project-transcription-16may \
  --display-name="Doc Transcribe Runtime"
```

Verification:
```bash
gcloud iam service-accounts list --project=my-project-transcription-16may | rg doc-transcribe-runtime
```
Expected: service account appears.

---

### 1.7 Grant IAM roles to service account
Set variables:
```bash
PROJECT_ID="my-project-transcription-16may"
BUCKET_NAME="my-project-transcription-16may-output"
SA_EMAIL="doc-transcribe-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
```

Grant bucket object admin:
```bash
gcloud storage buckets add-iam-policy-binding gs://${BUCKET_NAME} \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"
```

If OCR/transcription path needs Vertex AI access:
```bash
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user"
```

Verification:
```bash
gcloud storage buckets get-iam-policy gs://${BUCKET_NAME} \
  --format="table(bindings.role, bindings.members)"
```
Expected: SA appears under `roles/storage.objectAdmin`.

---

### 1.8 Create service account key JSON
Create key file:
```bash
mkdir -p ~/.gcp-keys
gcloud iam service-accounts keys create ~/.gcp-keys/doc-transcribe-runtime.json \
  --iam-account="${SA_EMAIL}" \
  --project="${PROJECT_ID}"
```

Lock permissions:
```bash
chmod 600 ~/.gcp-keys/doc-transcribe-runtime.json
```

Verification:
```bash
ls -l ~/.gcp-keys/doc-transcribe-runtime.json
cat ~/.gcp-keys/doc-transcribe-runtime.json | head -n 2
```
Expected:
- file exists
- JSON starts with `{`

---

### 1.9 Validate service account access end-to-end (local)
```bash
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.gcp-keys/doc-transcribe-runtime.json"
echo "healthcheck $(date)" > /tmp/gcs-healthcheck.txt
gcloud storage cp /tmp/gcs-healthcheck.txt gs://my-project-transcription-16may-output/healthcheck.txt
gcloud storage cp gs://my-project-transcription-16may-output/healthcheck.txt /tmp/gcs-healthcheck-downloaded.txt
cat /tmp/gcs-healthcheck-downloaded.txt
```

Verification:
- upload succeeds
- download succeeds
- file content matches

---

## 2) Render Setup (API + Redis Only)

### 2.1 Create Redis service
1. Open [Render Dashboard](https://dashboard.render.com/).
2. Select the correct workspace/team (top-left workspace selector).
3. Click `New +` -> `Redis`.
4. Configure:
   - Name: `doc-transcribe-redis`
   - Region: choose nearest region to your users/workers
   - Plan: select suitable plan (starter is fine for initial setup)
5. Click `Create Redis`.
6. Open created Redis service page -> `Connect` / `Info`.
7. Copy internal connection string (`REDIS_URL`) for API + local worker use.

Verification:
- Redis service status is `Available`
- `REDIS_URL` visible in Render

### 2.2 Create API service (`doc-transcribe-api`)
1. Open [Render Dashboard](https://dashboard.render.com/).
2. Confirm same workspace/team where Redis was created.
3. Click `New +` -> `Web Service`.
4. Connect Git provider (GitHub) if not already connected.
5. Select repository `doc-transcribe-api`.
6. Configure web service:
   - Name: `doc-transcribe-api`
   - Branch: `main`
   - Region: same or nearby region as Redis
   - Runtime: Python
   - Build command: as defined in repo
   - Start command: as defined in repo
7. Add service account JSON as Render Secret File:
   - In API service page, open `Environment` -> `Secret Files`
   - Filename: `gcp-sa.json`
   - Contents: paste full JSON from `~/.gcp-keys/doc-transcribe-runtime.json`
   - Render mounts it at `/etc/secrets/gcp-sa.json`
8. Open `Environment` section and add env vars:
   - `GCS_BUCKET_NAME=my-project-transcription-16may-output`
   - `REDIS_URL=<from Render Redis>`
   - `QUEUE_NAME=doc_jobs`
   - `CORS_ALLOW_ORIGINS=<your vercel domain>`
   - `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/gcp-sa.json`
9. Click `Create Web Service` / `Deploy`.
10. After first deploy, open service `Logs` and `Events`.

Verification:
- Deploy logs succeed
- API health endpoint returns 200
 - API logs include GCP identity/config lines:
   - `api_gcp_config bucket=... credentials_path=... credentials_json_set=...`
   - `gcloud_active_account=...`
   - `gcp_identity source=... project=... service_account=...`
 - Exact strings to search in API logs:
   - `api_gcp_config`
   - `gcloud_active_account=`
   - `gcp_identity source=`
 - Example command (if logs are saved locally):
```bash
grep -E "api_gcp_config|gcloud_active_account=|gcp_identity source=" /tmp/api.log
```

## 3) Vercel Setup (UI)

1. Vercel -> `Add New Project`
2. Import `doc-transcribe-ui` repo
3. Keep framework/build settings as required by repo
4. Get `API_BASE_URL` from Render API service:
   - Open [Render Dashboard](https://dashboard.render.com/)
   - Open service `doc-transcribe-api`
   - Copy public service URL from the service overview (example: `https://doc-transcribe-api.onrender.com`)
   - Use this exact value as `API_BASE_URL`
5. Add env vars:
   - `API_BASE_URL=<copied Render API URL>`
   - Any auth vars used by UI (example Google client ID)
6. Deploy

Verification:
- UI URL opens
- browser console has no startup errors
- network call to `/upload` reaches Render API

---

## 4) Local Worker Setup (Not on Render)

### 4.1 Local worker `.zshrc` setup

Get values first:
1. `GCP_PROJECT_ID`
   - Run:
```bash
gcloud config get-value project
```
   - Use returned value (example: `my-project-transcription-16may`)
2. `GCS_BUCKET_NAME`
   - Use bucket created in step `1.5` (example: `my-project-transcription-16may-output`)
   - Verify:
```bash
gcloud storage buckets list --project my-project-transcription-16may
```
3. `REDIS_URL`
   - Open [Render Dashboard](https://dashboard.render.com/)
   - Open Redis service `doc-transcribe-redis`
   - Copy **external** connection string from `Connect`/`Info` (local machine cannot access Render private internal network)
   - Use external `rediss://...` value as local worker `REDIS_URL`
4. `QUEUE_MODE`
   - Use `single` for this setup (one queue for worker consumption)
   - Source: worker runtime configuration in this guide (local worker mode)
5. `QUEUE_NAME`
   - Use `doc_jobs`
   - Source: keep same value as API env var `QUEUE_NAME` in Render step `2.2`
6. `DLQ_NAME`
   - Use `doc_jobs_dead`
   - Source: worker single-queue DLQ convention used in this setup

Add to `~/.zshrc`:
```bash
export GCP_PROJECT_ID="my-project-transcription-16may"
export GCS_BUCKET_NAME="my-project-transcription-16may-output"
export REDIS_URL="rediss://<your-render-redis-url>"
export QUEUE_MODE="single"
export QUEUE_NAME="doc_jobs"
export DLQ_NAME="doc_jobs_dead"
export OCR_PAGE_BATCH_SIZE="25"
export GEMINI_429_COOLDOWN_SEC="60"
export GEMINI_429_COOLDOWN_LOG_INTERVAL_SEC="10"
export GEMINI_429_MAX_COOLDOWNS_PER_PAGE="30"
export PROMPT_FILE="prompts/prompt.txt"
export PROMPT_NAME="PRAVACHAN_PROMPT"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.gcp-keys/doc-transcribe-runtime.json"
```

Cooldown variable meaning:
- `GEMINI_429_COOLDOWN_SEC`: cooldown wait in seconds when Gemini returns `429 ResourceExhausted`.
- `GEMINI_429_COOLDOWN_LOG_INTERVAL_SEC`: log interval during cooldown wait.
- `GEMINI_429_MAX_COOLDOWNS_PER_PAGE`: max cooldown cycles for one page before failing.

Load config:
```bash
source ~/.zshrc
```

Verification:
```bash
env | grep -E "GCP_PROJECT_ID|GCS_BUCKET_NAME|QUEUE_NAME|DLQ_NAME|GOOGLE_APPLICATION_CREDENTIALS|GEMINI_429_COOLDOWN_SEC|GEMINI_429_COOLDOWN_LOG_INTERVAL_SEC|GEMINI_429_MAX_COOLDOWNS_PER_PAGE"
```
Expected: all values appear.

### 4.2 Start worker locally
From worker repo directory:
```bash
cd /Users/arpit/Documents/Codex/2026-04-30-import-repos-https-github-com-arpit/doc-transcribe-worker
python3 -m venv .venv
source .venv/bin/activate
python --version
pip install -r requirements.txt
source ~/.zshrc
python -m worker.worker_loop
```
Important:
- `python --version` must show `3.x` before running worker.
- If you see Python `2.7`, stop and re-activate `.venv`.


Verification:
- Worker starts without startup env errors
- Logs show queue polling started
- On job submission, logs show job picked and processed
 - Worker logs include GCP identity/config lines:
   - `worker_gcp_config project_id=... bucket=... credentials_path=... credentials_json_set=...`
   - `gcloud_active_account=...`
   - `gcp_identity source=... project=... service_account=...`
 - Exact strings to search in worker logs:
   - `worker_gcp_config`
   - `gcloud_active_account=`
   - `gcp_identity source=`
 - Example command:
```bash
grep -E "worker_gcp_config|gcloud_active_account=|gcp_identity source=" /tmp/worker-live.log
```

### 4.3 Cleanup queued/inflight jobs (local ops)
If you need to clear stuck/pending jobs:

```bash
cd /Users/arpit/Documents/Codex/2026-04-30-import-repos-https-github-com-arpit/doc-transcribe-worker
source .venv/bin/activate
python - <<'PY'
import os, redis
r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

keys = [
    "doc_jobs",
    "doc_jobs_dead",
    "worker:inflight:OCR",
    "worker:inflight:TRANSCRIPTION",
    "worker:inflight:OTHER",
]

for k in keys:
    t = r.type(k)
    size = r.llen(k) if t == "list" else r.scard(k) if t == "set" else 0
    print(f"{k} before: type={t} size={size}")

r.delete(*keys)

for k in keys:
    print(f"{k} after: type={r.type(k)}")
PY
```

If a specific job keeps reappearing, remove its status hash too:
```bash
cd /Users/arpit/Documents/Codex/2026-04-30-import-repos-https-github-com-arpit/doc-transcribe-worker
source .venv/bin/activate
python - <<'PY'
import os, redis
r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
job_id = "<JOB_ID>"
k = f"job_status:{job_id}"
print("exists before:", r.exists(k))
r.delete(k)
print("exists after:", r.exists(k))
PY
```

---

## 5) End-to-End Smoke Test

1. Open UI (Vercel URL)
2. Upload a small MP3
3. Verify API returns `200` on upload
4. Verify worker logs:
   - job picked
   - GCS download success
   - transcription completed
5. Verify UI history/status shows completion and transcript output

Verification:
- No `403 storage.objects.get` in worker logs
- transcript text is generated

---

## 6) Quick Troubleshooting Map

- `403 storage.objects.get denied`:
  - wrong service account or missing bucket IAM (`roles/storage.objectAdmin` / `roles/storage.objectViewer`)

- credential parse errors:
  - invalid service account JSON file path/content
  - verify `GOOGLE_APPLICATION_CREDENTIALS` points to a valid JSON key file

- API upload 200 but worker fails:
  - API and worker env mismatch (`GCS_BUCKET_NAME`, `GCP_PROJECT_ID`, credentials)
