# Doc Transcribe Worker Setup Guide

This guide captures all setup and fixes we applied so far, step by step, with exact commands.

## 1) Clone repos

```bash
git clone https://github.com/arpit-jain-mygit/doc-transcribe-worker.git
git clone https://github.com/arpit-jain-mygit/doc-transcribe-api.git
git clone https://github.com/arpit-jain-mygit/doc-transcribe-ui.git
```

## 2) Go to worker project

```bash
cd /Users/arpit/Documents/Codex/2026-04-30-import-repos-https-github-com-arpit/doc-transcribe-worker
```

## 3) Install Python 3.11 using `uv` (since system Python was 3.8)

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install Python 3.11:

```bash
~/.local/bin/uv python install 3.11
```

## 4) Create fresh virtual environment and install dependencies

```bash
rm -rf .venv
~/.local/bin/uv venv --python 3.11 .venv
source .venv/bin/activate
python -m ensurepip --upgrade
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 5) Fix and persist shell environment (`~/.zshrc`)

Use this final content:

```bash
export REDIS_URL="rediss://red-d5qsp2h5pdvs739chvk0:CVelHOZknm6PVA83cDOlPDlaHLRkSZk8@singapore-keyvalue.render.com:6379"
export QUEUE_NAME="doc_jobs"
export DLQ_NAME="doc_jobs_dead"
export GEMINI_API_KEY="AIzaSyC8sUh7vij0YqK9m8pv4VVFpwfjQWmH2P8"
export PROMPT_FILE="prompts/prompt.txt"
export PROMPT_NAME="PRAVACHAN_PROMPT"
export GCP_PROJECT_ID="transcribe-serverless"
export GCS_BUCKET_NAME="doc-transcribe-output-transcribe-serverless"
export GOOGLE_APPLICATION_CREDENTIALS="/Users/arpit/Downloads/doc-transcribe-worker.json"

. "$HOME/.local/bin/env"
```

Then reload shell:

```bash
source ~/.zshrc
```

## 6) Google Cloud credentials (ADC)

Download service account JSON from:
- Google Cloud Console -> Project `transcribe-serverless` -> IAM & Admin -> Service Accounts -> (worker account) -> Keys -> Add Key -> Create new key -> JSON

Store it at:

```bash
/Users/arpit/Downloads/doc-transcribe-worker.json
```

Verify file exists:

```bash
ls -l /Users/arpit/Downloads/doc-transcribe-worker.json
```

Optional ADC check:

```bash
gcloud auth application-default print-access-token
```

## 7) Run worker

From worker folder:

```bash
source ~/.zshrc
source .venv/bin/activate
python -m worker.worker_loop
```

## 8) Known runtime errors and fixes

### Error: `SyntaxError` from Python 2.7
Cause: using `python` mapped to Python 2.
Fix: use Python 3.11 virtualenv and run with active `.venv`.

### Error: `ModuleNotFoundError: redis`
Cause: dependencies not installed.
Fix:

```bash
python -m pip install -r requirements.txt
```

### Error: `No matching distribution found for google-genai`
Cause: Python 3.8 incompatibility in environment.
Fix: move to Python 3.11 and recreate `.venv`.

### Error: `startup_env_invalid ... is required`
Cause: missing env vars.
Fix: set all required env vars in `~/.zshrc` (section 5).

### Error: `redis.exceptions.ConnectionError ... Error 8`
Cause: network/DNS restriction in restricted shell.
Fix: run with normal network-enabled shell/environment.

### Error: `DefaultCredentialsError: Your default credentials were not found`
Cause: missing ADC/service account config.
Fix: set

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/Users/arpit/Downloads/doc-transcribe-worker.json"
```

### Error: `FileNotFoundError: ffprobe`
Cause: FFmpeg/ffprobe not installed.
Fix: install FFmpeg system-wide.

If Homebrew is available:

```bash
brew install ffmpeg
ffprobe -version
```

If Homebrew is not installed, install Homebrew first:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install ffmpeg
ffprobe -version
```

## 9) Quick health checks

```bash
source ~/.zshrc
source .venv/bin/activate
python --version
python -m pip --version
python -c "import redis, requests, google.genai; print('python deps ok')"
ffprobe -version
python -m worker.worker_loop
```

Expected healthy worker logs include:
- `startup_env_validated`
- `Redis connection successful`
- `Entering BRPOP wait targets=['doc_jobs']`

## 10) Fast fallback when Homebrew `ffmpeg` install is too slow on macOS 12

If `brew install ffmpeg` gets stuck compiling dependencies (especially `cmake`) for a long time, use this direct `ffprobe` install.

Stop stuck brew builds:

```bash
pkill -f '/opt/homebrew/Library/Homebrew/brew.rb install ffmpeg|build.rb .*cmake|brew install ffmpeg' || true
```

Install standalone `ffprobe` binary:

```bash
mkdir -p ~/.local/bin
curl -L 'https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip' -o /tmp/ffprobe.zip
unzip -o /tmp/ffprobe.zip -d /tmp
mv /tmp/ffprobe ~/.local/bin/ffprobe
chmod +x ~/.local/bin/ffprobe
```

Verify:

```bash
~/.local/bin/ffprobe -version
which ffprobe
```

Note:
- This fixes `FileNotFoundError: [Errno 2] No such file or directory: 'ffprobe'`.
- You may still see `pydub` warning about missing `ffmpeg` (different binary). If your pipeline needs full transcoding, install full `ffmpeg` later.

## 11) Fix for `FileNotFoundError: ffmpeg`

If job fails with:
- `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`
- DLQ error code like `MEDIA_DECODE_FAILED`

Install standalone `ffmpeg` binary:

```bash
mkdir -p ~/.local/bin
curl -L 'https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip' -o /tmp/ffmpeg.zip
unzip -o /tmp/ffmpeg.zip -d /tmp
mv /tmp/ffmpeg ~/.local/bin/ffmpeg
chmod +x ~/.local/bin/ffmpeg
```

Verify:

```bash
which ffmpeg
ffmpeg -version
```

Then rerun worker:

```bash
source ~/.zshrc
source .venv/bin/activate
python -m worker.worker_loop
```

## 12) Fix for `binascii.Error: Incorrect padding` (GCS credential decode)

### Symptom
Worker fails during GCS download with stack trace ending in:

- `binascii.Error: Incorrect padding`
- From `worker/utils/gcs.py` while doing `base64.b64decode(creds_b64)`

### Cause
`GOOGLE_APPLICATION_CREDENTIALS_JSON` is set in shell/session, and worker tries to base64-decode it.
If this variable contains a file path or non-base64 text, decode fails.

### Correct approach (used in this setup)
Use file-path based credentials only:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/Users/arpit/Downloads/doc-transcribe-worker.json"
```

And ensure `GOOGLE_APPLICATION_CREDENTIALS_JSON` is not set.

### .zshrc fix applied
- Removed any `GOOGLE_APPLICATION_CREDENTIALS_JSON` entry from `~/.zshrc`
- Kept:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/Users/arpit/Downloads/doc-transcribe-worker.json"
```

### Apply in current shell

```bash
source ~/.zshrc
unset GOOGLE_APPLICATION_CREDENTIALS_JSON
```

### Verify

```bash
echo "$GOOGLE_APPLICATION_CREDENTIALS"
echo "$GOOGLE_APPLICATION_CREDENTIALS_JSON"
```

Expected:
- first prints `/Users/arpit/Downloads/doc-transcribe-worker.json`
- second is empty

### Run worker again

```bash
cd /Users/arpit/Documents/Codex/2026-04-30-import-repos-https-github-com-arpit/doc-transcribe-worker
source .venv/bin/activate
python -m worker.worker_loop
```
