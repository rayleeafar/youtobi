# Dual Upload & Video Secondary Creation Implementation Plan

> **Goal:** Support uploading to both Bilibili and YouTube accounts, and provide video secondary creation capabilities (horizontal image mirroring, configurable black border padding for scaling, and extreme-contrast invisible watermarking).

## Tasks Overview

- [ ] **Task 1: Config Management & Default Settings**
  - Add YouTube API and Video Secondary Creation settings to `config.py` and `config.example.json`.
  - Add unit tests for new configurations in `tests/test_youtobi.py`.

- [ ] **Task 2: Video Secondary Creation Engine (`services/video_editor.py`)**
  - Build `VideoEditor` class supporting horizontal flip (`hflip`), configurable border ratio (`pad`), and extreme-contrast invisible watermark (`drawtext`).
  - Integrate unified filter chain with subtitle burn-in.
  - Add unit tests for filter generation and video transformation.

- [ ] **Task 3: YouTube Data API v3 Uploader (`services/youtube_uploader.py`)**
  - Implement `YouTubeUploaderService` with OAuth2 token refresh, chunked resumable upload, progress callback, metadata, and thumbnail assignment.
  - Add unit tests with mock HTTP responses in `tests/test_youtobi.py`.

- [ ] **Task 4: Task Manager Multi-Platform Orchestration (`services/task_manager.py`)**
  - Update `Task` class with `upload_targets`, `secondary_creation`, `youtube_video_id`, `youtube_url_link`.
  - Update `_run_task_pipeline` to run secondary video creation and publish to selected destinations (Bilibili, YouTube, or Both).
  - Add unit tests for pipeline orchestration.

- [ ] **Task 5: API Endpoints & YouTube OAuth Helpers (`app.py`)**
  - Add `/api/youtube/auth-url`, `/api/youtube/oauth-callback`, `/api/youtube/test`.
  - Update `/api/tasks` schema to accept upload targets and secondary creation settings.
  - Add unit tests for API routes.

- [ ] **Task 6: Frontend UI & Interactive Controls**
  - Update `templates/index.html` with Upload Target selector, Secondary Creation accordion, and YouTube settings section.
  - Update `static/js/app.js` with dynamic form handling, YouTube OAuth test wizard, and dual-link task card rendering.
  - Update `static/css/style.css` with styling for target badges and secondary creation controls.

- [ ] **Task 7: Verification, Test Suite & Remote Deployment**
  - Run full pytest test suite locally.
  - Commit all changes incrementally.
  - Deploy to remote server `ubuntu@tencent-jp` via rsync.
  - Run remote test suite, restart systemd service, and verify remote endpoint health.
