# Design Spec: Dual Upload (Bilibili & YouTube) and Video Secondary Creation Engine

**Date**: 2026-08-19
**Status**: Approved
**Goal**: Support multi-platform publishing (Bilibili, YouTube, or Both) and provide a rich secondary creation engine (mirroring, border padding, extreme-contrast invisible watermark, slight speed tuning) to enhance content safety and customization.

---

## 1. Architecture Overview

```
                      +-----------------------------+
                      |       Input Task/Batch      |
                      | (Targets, Secondary Options)|
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |   1. YouTube Download       |
                      |  (Auto CookieCloud Sync)    |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |   2. Subtitle Processing    |
                      |  (Whisper STT / Translate)  |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      | 3. Video Secondary Engine   |
                      | - Horizontal Mirror (hflip) |
                      | - Configurable Black Border |
                      | - Invisible Contrast Mark   |
                      | - Subtitle Burn-In Combined |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |    4. LLM AI Metadata       |
                      |  (Title, Desc, Tags, Cat)   |
                      +--------------+--------------+
                                     |
                    +----------------+----------------+
                    |                                 |
                    v                                 v
      +----------------------------+    +----------------------------+
      |  5A. Bilibili Uploader     |    |  5B. YouTube Uploader      |
      |  - Chunked Member Upload   |    |  - Resumable Data API v3   |
      |  - SESSDATA & bili_jct     |    |  - OAuth2 / Refresh Token  |
      +----------------------------+    +----------------------------+
```

---

## 2. Component Specifications

### 2.1 Video Secondary Creation Engine (`services/video_editor.py`)
Provides modular FFmpeg filter chain generation that integrates with subtitle burn-in in a single re-encode pass for optimal performance:
1. **Horizontal Mirroring**:
   - Filter: `hflip`.
   - Flips image horizontally to avoid automated perceptual hash fingerprint matching.
2. **Configurable Black Border / Margin Padding**:
   - Options: `border_ratio` (0.0 to 0.20, default 0.05 / 5%).
   - Filter: `scale=iw*(1-2*ratio):ih*(1-2*ratio),pad=iw/(1-2*ratio):ih/(1-2*ratio):(ow-iw)/2:(oh-ih)/2:black`.
   - Normalizes output aspect ratio while preserving original resolution.
3. **Extreme-Contrast Invisible Watermark**:
   - Invisible under standard viewing (alpha 0.008 ~ 0.015).
   - Revealed under high-contrast / curves adjustment.
   - Filter using `drawtext` with low opacity or subtle alpha blend:
     `drawtext=text="%{text}":fontcolor=white@0.012:fontsize=h/25:x=(w-tw)/2:y=h*0.85:shadowcolor=black@0.012:shadowx=1:shadowy=1`.
4. **Combined Filter Pipeline**:
   - Chains `hflip` -> `scale/pad` -> `subtitles=...` -> `drawtext=...` into a unified `-vf` filtergraph to avoid multiple encoding iterations.

### 2.2 YouTube Data API v3 Resumable Uploader (`services/youtube_uploader.py`)
- Direct integration with Google YouTube Data API v3 (`https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status`).
- **OAuth2 Token Refresh**:
  - Automatically refreshes access tokens using `client_id`, `client_secret`, and `refresh_token`.
- **Resumable Chunked Upload**:
  - Uploads video chunks (default chunk size 4MB to 16MB) with resume-on-interruption support.
  - Updates task progress dynamically.
- **Metadata Configuration**:
  - `title`, `description`, `tags`, `category_id` (default 22: People & Blogs), `privacy_status` (`public`, `private`, `unlisted`).
- **Thumbnail Setting**:
  - Automatically uploads cover image thumbnail via `youtube.thumbnails.set` API if present.

### 2.3 Task & Pipeline Orchestration (`services/task_manager.py`)
- New Task parameters:
  - `upload_targets`: `["bilibili"]`, `["youtube"]`, or `["bilibili", "youtube"]` (or comma-separated / list).
  - `secondary_creation`: Dict with `{flip_horizontal: bool, border_ratio: float, watermark_text: str, watermark_enabled: bool}`.
- Pipeline execution:
  - Executes secondary video creation filter graph.
  - Sequentially uploads to all requested target platforms.
  - Sets `task.bvid` and `task.youtube_video_id` (`task.yt_url`).
  - Reports status and log messages for both upload platforms.

### 2.4 Configuration Management (`config.py` & `config.json`)
New configurations:
- `upload_targets`: Default `["bilibili"]` or `["bilibili", "youtube"]`.
- `youtube_upload_enabled`: Boolean.
- `youtube_client_id`: OAuth2 Client ID.
- `youtube_client_secret`: OAuth2 Client Secret.
- `youtube_refresh_token`: OAuth2 Refresh Token.
- `youtube_privacy_status`: `public` | `unlisted` | `private` (default `unlisted`).
- `youtube_category_id`: YouTube category ID (default `22`).
- `secondary_creation_enabled`: Boolean default `False`.
- `secondary_flip_horizontal`: Boolean default `False`.
- `secondary_border_ratio`: Float default `0.0` (range 0.0 - 0.20).
- `secondary_watermark_enabled`: Boolean default `False`.
- `secondary_watermark_text`: String default `""`.
- `secondary_watermark_opacity`: Float default `0.012`.

### 2.5 API Endpoints (`app.py`)
- `POST /api/tasks`: Accepts `upload_targets`, `secondary_creation` parameters.
- `POST /api/youtube/auth-url`: Generates Google OAuth2 consent URL for easy authorization.
- `POST /api/youtube/oauth-callback`: Exchanges OAuth2 code for refresh token and updates config.
- `POST /api/youtube/test`: Tests YouTube API credentials and returns channel info.

### 2.6 Frontend UI (`templates/index.html` & `static/js/app.js` & `static/css/style.css`)
- **Upload Target Selector**:
  - Target selection buttons/checkboxes: `Bilibili Only 📺`, `YouTube Only 🔴`, `Both Platforms 🚀`.
- **Secondary Creation Accordion / Panel**:
  - Mirroring toggle (水平翻转).
  - Edge border slider (黑边缩放比例 0% - 20%).
  - Extreme contrast invisible watermark input (极值对比度隐形防盗水印).
- **Settings Modal**:
  - YouTube Data API v3 configuration section with OAuth2 authorization wizard and test button.
- **Task Cards**:
  - Displays badges for upload targets and shows both Bilibili BV link and YouTube video link on completion.

---

## 3. Testing Strategy
- Unit tests in `tests/test_youtobi.py`:
  - Test video filter string construction in `VideoEditor`.
  - Test YouTube OAuth2 token refresh and resumable chunk logic.
  - Test task creation and pipeline execution with dual upload targets.
  - Test API endpoints (`/api/youtube/test`, `/api/youtube/auth-url`, task creation with secondary creation parameters).
- Remote deployment testing on `ubuntu@tencent-jp`.
