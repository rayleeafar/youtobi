# Design Spec: `youtobi` Batch Support, Whisper STT & UI Enhancements

**Date**: 2026-08-03
**Status**: Approved

## 1. Overview
`youtobi` is a YouTube to Bilibili video automation engine. This specification details three major enhancements:
1. **Batch & Playlist Support**: Process multiple YouTube URLs or full playlist URLs.
2. **Auto-Transcription (Whisper STT)**: Automatically transcribe audio to SRT subtitles using Whisper API when native subtitles are absent.
3. **UI & Lifecycle Workflow Controls**: Add task control operations (cancel, retry, delete), video stream preview, and FFmpeg encoding preset configurations.

---

## 2. Component Specifications

### 2.1 Batch & Playlist Processor (`services/youtube.py` & `services/task_manager.py`)
- **Playlist Extraction**: Use `yt-dlp` flat playlist metadata extraction (`yt-dlp --flat-playlist -j`) to resolve playlist URLs into individual video URLs.
- **Batch Enqueue**: Support parsing multi-line text or comma-separated lists of URLs. Batch requests expand into individual `Task` objects linked by a `batch_id`.

### 2.2 Whisper STT Auto-Transcription (`services/subtitle.py` & `services/llm.py`)
- **Audio Extraction**: Use `ffmpeg -i <video> -vn -acodec libmp3lame -q:a 2 <audio.mp3>` to extract video audio.
- **Whisper API Call**: Transcribe audio via OpenAI Audio Transcription API (`v1/audio/transcriptions`).
- **Subtitle Generation**: Save transcribed segments into standard `.srt` format with timestamps before passing to subtitle translation and burn-in.

### 2.3 Task Controls & API Endpoints (`app.py` & `services/task_manager.py`)
- `POST /api/tasks/{task_id}/cancel`: Sets cancel flag and kills active subprocesses (FFmpeg / yt-dlp).
- `POST /api/tasks/{task_id}/retry`: Resets task state to `PENDING` and re-triggers execution.
- `DELETE /api/tasks/{task_id}`: Cancels task if running, cleans up task directory and downloaded files, removes task record.
- `GET /api/tasks/{task_id}/stream`: Serves the processed MP4 video file with range-request video streaming support.

### 2.4 Config Manager (`config.py` & `config.json`)
New fields:
- `ffmpeg_preset`: Compression preset (`ultrafast`, `fast`, `medium`, `slow`). Default `fast`.
- `whisper_enabled`: Boolean flag.
- `whisper_api_key`: Secret API key for Whisper provider (defaults to `llm_api_key` if unset).
- `whisper_base_url`: Endpoint URL for Whisper provider (defaults to `llm_base_url` if unset).
- `whisper_model`: Model name (default `whisper-1`).

### 2.5 Frontend Dashboard (`templates/index.html` & `static/js/app.js` & `static/css/style.css`)
- **Input Area**: Multi-line URL input box with playlist detection badge.
- **Task Cards**:
  - Displays real-time status, progress bar, logs drawer.
  - Action buttons: **Preview (🎬)**, **Retry (🔄)**, **Cancel (⏹️)**, **Delete (🗑️)**.
- **Video Preview Modal**: In-page modal with HTML5 `<video>` player pointing to `/api/tasks/{task_id}/stream`.
- **Settings Drawer**: Extended with Whisper STT options & FFmpeg preset selection dropdown.

---

## 3. Deployment Plan (`ubuntu@43.167.173.71`)
- Scrape / package application codebase.
- Deploy to remote server via SSH.
- Setup systemd service (`youtobi.service`) or run daemon using python virtual environment.
- Verify web dashboard accessibility and health endpoint on port 8000.
