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

---

### 1.2 Create/select GCP project
1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Top bar project selector -> `New Project`
3. Project name: `my-project-transcription-12May` (or your final name)
4. Click `Create`
5. Select this project as active

Verification:
- Console top bar shows selected project
- CLI:
```bash
gcloud projects list --format="table(projectId,name)"
```
Important:
- `gcloud config set project` expects **projectId**, not project display name.
- Project IDs are usually lowercase (example: `my-project-transcription-12may`).

Set active project using **projectId**:
```bash
gcloud config set project <your-project-id>
gcloud config get-value project
```
Expected: output is your lowercase project ID.

If you see ADC quota warning, align it:
```bash
gcloud auth application-default set-quota-project <your-project-id>
```

---

### 1.3 Enable billing
1. Console -> `Billing`
2. Link your new project to billing account (free tier credits are okay)
3. If you see a red banner saying account must be verified, click `Verify account` and complete verification.
4. After verification, open `Billing` -> `Account management` -> `Projects linked` and confirm your project is listed.

Verification:
1. Red verification banner is no longer shown.
2. Billing page shows project linked.
2. CLI:
```bash
gcloud beta billing projects describe my-project-transcription-12May
```
Expected: `billingEnabled: true`

---

### 1.4 Enable required APIs
Enable APIs:
```bash
gcloud services enable storage.googleapis.com --project=my-project-transcription-12May
gcloud services enable aiplatform.googleapis.com --project=my-project-transcription-12May
```
If your worker uses specific generative APIs, enable those too per your model/provider.

Verification:
```bash
gcloud services list --enabled --project=my-project-transcription-12May | rg "storage|aiplatform"
```
Expected: both services appear.

---

### 1.5 Create GCS bucket
Pick globally unique bucket name, example:
- `my-project-transcription-12may-output`

Create:
```bash
gcloud storage buckets create gs://my-project-transcription-12may-output \
  --project=my-project-transcription-12May \
  --location=asia-south1 \
  --uniform-bucket-level-access
```

Verification:
```bash
gcloud storage buckets list --project=my-project-transcription-12May
gcloud storage ls gs://my-project-transcription-12may-output
```
Expected: bucket is listed and accessible.

---

### 1.6 Create service account for API/Worker
Create SA:
```bash
gcloud iam service-accounts create doc-transcribe-runtime \
  --project=my-project-transcription-12May \
  --display-name="Doc Transcribe Runtime"
```

Verification:
```bash
gcloud iam service-accounts list --project=my-project-transcription-12May | rg doc-transcribe-runtime
```
Expected: service account appears.

---

### 1.7 Grant IAM roles to service account
Set variables:
```bash
PROJECT_ID="my-project-transcription-12May"
BUCKET_NAME="my-project-transcription-12may-output"
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
gcloud storage cp /tmp/gcs-healthcheck.txt gs://my-project-transcription-12may-output/healthcheck.txt
gcloud storage cp gs://my-project-transcription-12may-output/healthcheck.txt /tmp/gcs-healthcheck-downloaded.txt
cat /tmp/gcs-healthcheck-downloaded.txt
```

Verification:
- upload succeeds
- download succeeds
- file content matches

---

## 2) Render Setup (API + Worker)

### 2.1 Create Redis service
1. Render dashboard -> `New` -> `Redis`
2. Name: `doc-transcribe-redis`
3. Create and copy internal `REDIS_URL`

Verification:
- Redis service status is `Available`
- `REDIS_URL` visible in Render

### 2.2 Create API service (`doc-transcribe-api`)
1. Render -> `New` -> `Web Service`
2. Connect repo `doc-transcribe-api`
3. Configure build/start command per repo
4. Add env vars:
   - `GCP_PROJECT_ID=my-project-transcription-12May`
   - `GCS_BUCKET_NAME=my-project-transcription-12may-output`
   - `REDIS_URL=<from Render Redis>`
   - `QUEUE_NAME=doc_jobs`
   - `CORS_ALLOW_ORIGINS=<your vercel domain>`
   - `GOOGLE_APPLICATION_CREDENTIALS_JSON=<contents of SA JSON OR path strategy used by your runtime>`
5. Deploy

Verification:
- Deploy logs succeed
- API health endpoint returns 200

### 2.3 Create Worker service (`doc-transcribe-worker`)
1. Render -> `New` -> `Background Worker`
2. Connect repo `doc-transcribe-worker`
3. Set start command per repo
4. Add env vars:
   - `GCP_PROJECT_ID=my-project-transcription-12May`
   - `GCS_BUCKET_NAME=my-project-transcription-12may-output`
   - `REDIS_URL=<from Render Redis>`
   - `QUEUE_MODE=single`
   - `QUEUE_NAME=doc_jobs`
   - `DLQ_NAME=doc_jobs_dead`
   - `PROMPT_FILE=prompts/prompt.txt`
   - `PROMPT_NAME=PRAVACHAN_PROMPT`
   - `GOOGLE_APPLICATION_CREDENTIALS_JSON=<same credential strategy as API>`
5. Deploy

Verification:
- Worker startup logs show env validation success
- No credential parse errors

---

## 3) Vercel Setup (UI)

1. Vercel -> `Add New Project`
2. Import `doc-transcribe-ui` repo
3. Keep framework/build settings as required by repo
4. Add env vars:
   - `API_BASE_URL=https://<your-api-service>.onrender.com`
   - Any auth vars used by UI (example Google client ID)
5. Deploy

Verification:
- UI URL opens
- browser console has no startup errors
- network call to `/upload` reaches Render API

---

## 4) Local Worker `.zshrc` Setup

Add to `~/.zshrc`:
```bash
export GCP_PROJECT_ID="my-project-transcription-12May"
export GCS_BUCKET_NAME="my-project-transcription-12may-output"
export REDIS_URL="rediss://<your-render-redis-url>"
export QUEUE_MODE="single"
export QUEUE_NAME="doc_jobs"
export DLQ_NAME="doc_jobs_dead"
export PROMPT_FILE="prompts/prompt.txt"
export PROMPT_NAME="PRAVACHAN_PROMPT"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.gcp-keys/doc-transcribe-runtime.json"
```

Load config:
```bash
source ~/.zshrc
```

Verification:
```bash
env | rg "GCP_PROJECT_ID|GCS_BUCKET_NAME|QUEUE_NAME|DLQ_NAME|GOOGLE_APPLICATION_CREDENTIALS"
```
Expected: all values appear.

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
  - malformed `GOOGLE_APPLICATION_CREDENTIALS_JSON`
  - use SA JSON content or stable path-based strategy

- API upload 200 but worker fails:
  - API and worker env mismatch (`GCS_BUCKET_NAME`, `GCP_PROJECT_ID`, credentials)
