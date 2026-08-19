# youtobi - YouTube to Bilibili Automation Engine

`youtobi` is a full-featured video automation pipeline and web application designed to automatically process YouTube videos and upload them to Bilibili.

## Features

1. **Web Dashboard**: Modern, glassmorphism dark-mode web UI for entering YouTube video URLs, configuring credentials, tracking progress in real-time, and reviewing logs.
2. **YouTube Video & Subtitle Downloader**: Powered by `yt-dlp` to download video streams and subtitles.
3. **Smart Subtitle Processing & Burn-In**:
   - Automatically detects if the video language is Chinese.
   - If the video is non-Chinese, extracts/generates Chinese subtitles and hardcodes (burns in) Chinese SRT subtitles into the video file using `ffmpeg`.
4. **LLM Description & Metadata Regeneration**:
   - If an LLM provider is configured (OpenAI, DeepSeek, Custom API Key & Base URL), reads the original YouTube video description and generates an engaging Bilibili-optimized title, description, and tags in Chinese.
   - If LLM is not configured, seamlessly falls back to the original YouTube title and description.
5. **Bilibili Auto-Upload**: Uploads processed videos directly to Bilibili member platform using SESSDATA and bili_jct cookies with line chunking.
6. **CookieCloud Integration**: Easily syncs fresh Bilibili session cookies from a CookieCloud server with one click.

## Architecture

```
youtobi/
├── app.py                  # FastAPI web server and API routes
├── config.py               # JSON configuration manager
├── requirements.txt        # Python dependencies
├── docs/refers/            # Cloned reference projects (Y2A-Auto, CookieCloud)
├── services/
│   ├── youtube.py          # YouTube video & metadata extractor
│   ├── subtitle.py         # Subtitle translation & ffmpeg burn-in engine
│   ├── llm.py              # LLM prompt manager & description generator
│   ├── bilibili.py         # Bilibili upload API integration
│   ├── cookiecloud.py      # AES-128-CBC CookieCloud sync service
│   └── task_manager.py     # Background task runner & logger
├── templates/
│   └── index.html          # Frontend dashboard UI
└── static/
    ├── css/style.css       # Visual styles
    └── js/app.js           # Client-side interaction logic
```

## Quick Start

### 1. Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run Application
```bash
python3 app.py
```
Open `http://localhost:8000` in your web browser.

### 3. Usage
1. Open **Settings (⚙️)** in the web UI.
2. Optional: Configure LLM Provider (API Key, Base URL, Model name).
3. Optional: Configure Bilibili SESSDATA or sync from CookieCloud.
4. Enter a YouTube URL and click **Start Processing**.
