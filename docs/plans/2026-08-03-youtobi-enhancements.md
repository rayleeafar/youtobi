# `youtobi` Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement batch/playlist support, Whisper STT auto-transcription, task lifecycle controls (cancel, retry, delete, video preview stream), and deploy the updated application to remote server `ubuntu@43.167.173.71`.

**Architecture:** Extend FastAPI server endpoints, update `YouTubeService` to parse playlists/batch URLs, add audio extraction & Whisper STT fallback in `SubtitleService`, update `TaskManager` with task cancel/retry/delete capabilities, enhance visual glassmorphism UI with multi-input and video stream preview modal.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, yt-dlp, FFmpeg, PyCryptodome, Jinja2, HTML5/CSS3/JavaScript.

## Global Constraints
- Commit changes at every step (Git rule).
- Retain existing unit tests and ensure all tests pass cleanly.

---

### Task 1: Config Management & Whisper / FFmpeg Settings

**Files:**
- Modify: `youtobi/config.py`
- Modify: `youtobi/config.json`
- Test: `youtobi/tests/test_youtobi.py`

**Interfaces:**
- Consumes: JSON config stored in `config.json`.
- Produces: `config_manager.all()` providing `ffmpeg_preset`, `whisper_enabled`, `whisper_api_key`, `whisper_base_url`, `whisper_model`.

- [ ] **Step 1: Write test for new config properties**

Modify `youtobi/tests/test_youtobi.py` to add `test_config_whisper_and_ffmpeg_defaults()`.

```python
def test_config_whisper_and_ffmpeg_defaults():
    from config import config_manager
    cfg = config_manager.all()
    assert "ffmpeg_preset" in cfg
    assert "whisper_enabled" in cfg
    assert cfg["ffmpeg_preset"] in ["ultrafast", "fast", "medium", "slow"]
```

- [ ] **Step 2: Update `config.py` and `config.json`**

Update `config.py` to default `ffmpeg_preset`, `whisper_enabled`, `whisper_api_key`, `whisper_base_url`, `whisper_model`.

```python
DEFAULT_CONFIG = {
    "llm_enabled": False,
    "llm_provider": "openai",
    "llm_api_key": "",
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-3.5-turbo",
    "bilibili_sessdata": "",
    "bilibili_bili_jct": "",
    "bilibili_dedeuserid": "",
    "cookiecloud_url": "",
    "cookiecloud_uuid": "",
    "cookiecloud_password": "",
    "downloads_dir": "./downloads",
    "ffmpeg_preset": "fast",
    "whisper_enabled": True,
    "whisper_api_key": "",
    "whisper_base_url": "",
    "whisper_model": "whisper-1",
}
```

- [ ] **Step 3: Run pytest to verify**

Run: `./venv/bin/python -m pytest tests/test_youtobi.py -v` (with jinja2 installed)
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add youtobi/config.py youtobi/config.json youtobi/tests/test_youtobi.py
git commit -m "feat: add whisper and ffmpeg configuration options to config manager"
```

---

### Task 2: Playlist & Batch Video URL Parsing

**Files:**
- Modify: `youtobi/services/youtube.py`
- Modify: `youtobi/services/task_manager.py`
- Modify: `youtobi/app.py`
- Test: `youtobi/tests/test_youtobi.py`

**Interfaces:**
- Consumes: YouTube single URL, multi-line URLs, or Playlist URL (`youtube.com/playlist?list=...`).
- Produces: `YouTubeService.extract_urls(input_str)` returning list of individual YouTube URLs. `task_manager.create_batch_tasks(urls)`.

- [ ] **Step 1: Write test for URL extraction and batch task creation**

```python
def test_youtube_extract_urls():
    from services.youtube import YouTubeService
    urls_input = "https://www.youtube.com/watch?v=video1\nhttps://youtu.be/video2"
    urls = YouTubeService.extract_urls(urls_input)
    assert len(urls) == 2
    assert urls[0] == "https://www.youtube.com/watch?v=video1"
    assert urls[1] == "https://youtu.be/video2"
```

- [ ] **Step 2: Implement `extract_urls` in `services/youtube.py` and batch creation in `task_manager.py` & `app.py`**

- Add static method `YouTubeService.extract_urls(input_text: str) -> List[str]`.
- Support parsing playlist links via `yt-dlp --flat-playlist -j`.
- Update `create_task` in `app.py` to accept single or multiple URLs and return list of created tasks.

- [ ] **Step 3: Run pytest to verify**

Run: `./venv/bin/python -m pytest tests/test_youtobi.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add youtobi/services/youtube.py youtobi/services/task_manager.py youtobi/app.py youtobi/tests/test_youtobi.py
git commit -m "feat: add playlist extraction and batch URL task creation support"
```

---

### Task 3: Whisper STT Auto-Transcription Engine

**Files:**
- Modify: `youtobi/services/subtitle.py`
- Test: `youtobi/tests/test_youtobi.py`

**Interfaces:**
- Consumes: MP4 video file path, audio extraction via FFmpeg, Whisper API config.
- Produces: Timestamped Chinese `.srt` file.

- [ ] **Step 1: Write test for SRT formatting & audio extraction logic**

```python
def test_srt_formatting():
    from services.subtitle import SubtitleService
    segments = [
        {"start": 0.0, "end": 2.5, "text": "Hello world"},
        {"start": 2.5, "end": 5.0, "text": "Welcome to youtobi"}
    ]
    srt_content = SubtitleService.format_segments_to_srt(segments)
    assert "1" in srt_content
    assert "00:00:00,000 --> 00:00:02,500" in srt_content
    assert "Hello world" in srt_content
```

- [ ] **Step 2: Implement audio extraction and Whisper STT fallback in `SubtitleService`**

- Add `extract_audio(video_path: Path, output_mp3: Path)` using ffmpeg.
- Add `transcribe_with_whisper(audio_path: Path, config: dict)` calling OpenAI Audio Transcription endpoint (or HTTP request).
- Add `format_segments_to_srt(segments) -> str`.
- Connect into `process_subtitles()` when no subtitles exist on YouTube.

- [ ] **Step 3: Run pytest to verify**

Run: `./venv/bin/python -m pytest tests/test_youtobi.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add youtobi/services/subtitle.py youtobi/tests/test_youtobi.py
git commit -m "feat: implement Whisper STT audio transcription and SRT formatting"
```

---

### Task 4: Task Lifecycle Controls & Video Stream Endpoints

**Files:**
- Modify: `youtobi/services/task_manager.py`
- Modify: `youtobi/app.py`
- Test: `youtobi/tests/test_youtobi.py`

**Interfaces:**
- Consumes: Task ID.
- Produces: API endpoints `/api/tasks/{task_id}/cancel`, `/api/tasks/{task_id}/retry`, `DELETE /api/tasks/{task_id}`, and `/api/tasks/{task_id}/stream`.

- [ ] **Step 1: Write test for task cancel, retry, delete endpoints**

```python
def test_task_lifecycle_api(client):
    res = client.post("/api/tasks", json={"youtube_url": "https://www.youtube.com/watch?v=test12345"})
    assert res.status_code == 200
    task_id = res.json()["tasks"][0]["id"]
    
    # Cancel
    c_res = client.post(f"/api/tasks/{task_id}/cancel")
    assert c_res.status_code == 200
    
    # Retry
    r_res = client.post(f"/api/tasks/{task_id}/retry")
    assert r_res.status_code == 200

    # Delete
    d_res = client.delete(f"/api/tasks/{task_id}")
    assert d_res.status_code == 200
```

- [ ] **Step 2: Implement task cancel, retry, delete, and video streaming endpoints**

- Update `TaskManager` to track subprocess PIDs / cancellation tokens.
- Add methods: `cancel_task(task_id)`, `retry_task(task_id)`, `delete_task(task_id)`.
- Add route `@app.get("/api/tasks/{task_id}/stream")` returning `FileResponse` / Range requests for video playback.

- [ ] **Step 3: Run pytest to verify**

Run: `./venv/bin/python -m pytest tests/test_youtobi.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add youtobi/services/task_manager.py youtobi/app.py youtobi/tests/test_youtobi.py
git commit -m "feat: add task cancel, retry, delete endpoints and video stream response"
```

---

### Task 5: Web UI Dashboard Enhancement

**Files:**
- Modify: `youtobi/templates/index.html`
- Modify: `youtobi/static/js/app.js`
- Modify: `youtobi/static/css/style.css`

**Interfaces:**
- Consumes: Updated `/api/tasks`, `/api/config`, `/api/tasks/{task_id}/stream`, `/api/tasks/{task_id}/cancel`, `/api/tasks/{task_id}/retry`, `DELETE /api/tasks/{task_id}`.
- Produces: Glassmorphism interactive web UI.

- [ ] **Step 1: Update `index.html` with batch URL textarea, task action buttons, video modal, and Whisper / FFmpeg settings**
- [ ] **Step 2: Update `static/js/app.js` with batch URL submit handler, modal triggers, cancel/retry/delete API calls**
- [ ] **Step 3: Update `static/css/style.css` with responsive modal styles, action button styling, and badge design**
- [ ] **Step 4: Run manual / automated UI endpoint tests**

```bash
./venv/bin/python -m pytest tests/test_youtobi.py -v
```

- [ ] **Step 5: Commit**

```bash
git add youtobi/templates/index.html youtobi/static/js/app.js youtobi/static/css/style.css
git commit -m "feat: enhance UI dashboard with batch input, video modal preview, and task controls"
```

---

### Task 6: Comprehensive Test Verification & Dependencies Cleanup

**Files:**
- Modify: `youtobi/requirements.txt`
- Modify: `youtobi/tests/test_youtobi.py`

**Interfaces:**
- Consumes: Virtual environment & complete app stack.
- Produces: Passing test suite.

- [ ] **Step 1: Add missing dependencies to `requirements.txt` (jinja2, pytest)**
- [ ] **Step 2: Run full test suite to guarantee 100% pass rate**

```bash
./venv/bin/python -m pytest tests/test_youtobi.py -v
```

- [ ] **Step 3: Commit**

```bash
git add youtobi/requirements.txt youtobi/tests/test_youtobi.py
git commit -m "test: verify complete youtobi test suite and update requirements.txt"
```

---

### Task 7: Deployment to Remote Server (`ubuntu@43.167.173.71`)

**Files:**
- Target Server: `ubuntu@43.167.173.71`
- Remote Directory: `/home/ubuntu/youtobi` or `/opt/youtobi`

**Interfaces:**
- Consumes: Local `youtobi` repository.
- Produces: Running systemd service or background daemon on remote server accessible via HTTP port 8000.

- [ ] **Step 1: Test SSH connectivity to `ubuntu@43.167.173.71`**
- [ ] **Step 2: Rsync/scp `youtobi` application files to remote server**
- [ ] **Step 3: Install system dependencies (ffmpeg, python3-venv) and python packages on remote server**
- [ ] **Step 4: Configure systemd service `youtobi.service` and start application daemon**
- [ ] **Step 5: Verify remote health endpoint via `curl -I http://43.167.173.71:8000/`**
- [ ] **Step 6: Commit deployment records / scripts**

```bash
git commit --allow-empty -m "deploy: successfully deployed youtobi to ubuntu@43.167.173.71"
```
