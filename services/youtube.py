import os
import glob
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
import yt_dlp

logger = logging.getLogger("youtobi.youtube")

class YouTubeService:
    def __init__(self, downloads_dir: Path):
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def extract_items(input_text: str) -> List[Dict[str, Optional[str]]]:
        """
        Parses input text containing YouTube URLs and optional custom description lines starting with '#'.
        Returns a list of dicts: [{'url': '...', 'custom_text': '...'}, ...]
        """
        lines = [line.strip() for line in input_text.replace(",", "\n").splitlines() if line.strip()]
        items: List[Dict[str, Optional[str]]] = []
        
        current_url: Optional[str] = None
        current_text_lines: List[str] = []

        for line in lines:
            if line.startswith("#"):
                text = line.lstrip("#").strip()
                if text:
                    current_text_lines.append(text)
            else:
                inline_custom = None
                if " #" in line:
                    parts = line.split(" #", 1)
                    url_part = parts[0].strip()
                    inline_custom = parts[1].strip()
                else:
                    url_part = line.strip()

                if "youtube.com" in url_part or "youtu.be" in url_part:
                    if current_url:
                        items.append({
                            "url": current_url,
                            "custom_text": "\n".join(current_text_lines).strip() if current_text_lines else None
                        })
                        current_text_lines = []

                    current_url = url_part
                    if inline_custom:
                        current_text_lines.append(inline_custom)

        if current_url:
            items.append({
                "url": current_url,
                "custom_text": "\n".join(current_text_lines).strip() if current_text_lines else None
            })

        expanded_items: List[Dict[str, Optional[str]]] = []
        for item in items:
            url = item["url"]
            custom = item["custom_text"]
            if url and ("youtube.com/playlist" in url or "list=" in url):
                extracted_urls = YouTubeService.extract_urls(url)
                for u in extracted_urls:
                    expanded_items.append({"url": u, "custom_text": custom})
            elif url:
                expanded_items.append(item)

        return expanded_items

    @staticmethod
    def extract_urls(input_text: str) -> List[str]:
        """Extract individual YouTube video URLs from multi-line text, comma-separated lists, or playlists."""
        items = YouTubeService.extract_items(input_text)
        return [it["url"] for it in items if it.get("url")]


    def _get_cookie_file(self) -> Optional[str]:
        """Check for configured youtube_cookies file path or text string and return cookiefile path."""
        from config import config_manager
        cookies_val = config_manager.get("youtube_cookies", "").strip()
        if not cookies_val:
            return None
        
        # If cookies_val contains newlines, tabs, Netscape header or is long, treat directly as Netscape cookies text content
        if "\n" in cookies_val or "\t" in cookies_val or "Netscape" in cookies_val or len(cookies_val) > 250:
            temp_cookie_path = self.downloads_dir / "yt_cookies.txt"
            try:
                temp_cookie_path.write_text(cookies_val, encoding="utf-8")
                return str(temp_cookie_path)
            except Exception as e:
                logger.error(f"Failed writing yt_cookies.txt: {e}")
                return None

        # Check if cookies_val is a valid existing file path
        try:
            p = Path(cookies_val)
            if p.exists() and p.is_file():
                return str(p)
        except Exception:
            pass

        temp_cookie_path = self.downloads_dir / "yt_cookies.txt"
        try:
            temp_cookie_path.write_text(cookies_val, encoding="utf-8")
            return str(temp_cookie_path)
        except Exception:
            return None


    def extract_info(self, url: str) -> Dict[str, Any]:
        """Extract metadata for YouTube video without downloading video stream."""
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "remote_components": ["ejs:github"],
        }
        cookie_file = self._get_cookie_file()
        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        title = info.get("title", "Untitled")
        description = info.get("description", "")
        language = info.get("language") or info.get("lang") or ""
        duration = info.get("duration", 0)
        thumbnail = info.get("thumbnail", "")
        uploader = info.get("uploader", "")
        subtitles = info.get("subtitles", {})
        automatic_captions = info.get("automatic_captions", {})
        
        # Determine language heuristic if missing from metadata
        is_chinese = self._check_is_chinese(language, title, description)

        return {
            "id": info.get("id"),
            "url": url,
            "title": title,
            "description": description,
            "language": language,
            "is_chinese": is_chinese,
            "duration": duration,
            "thumbnail": thumbnail,
            "uploader": uploader,
            "has_subtitles": bool(subtitles or automatic_captions),
            "subtitles_keys": list((subtitles or {}).keys()),
            "auto_subtitles_keys": list((automatic_captions or {}).keys()),
        }

    def _check_is_chinese(self, language: str, title: str, description: str) -> bool:
        if language and any(code in language.lower() for code in ["zh", "chi", "zho"]):
            return True
        # Check text ratio of Chinese characters
        text = (title + " " + description[:200])
        if not text.strip():
            return False
        cjk_count = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        return (cjk_count / len(text)) > 0.25

    def download_video_and_subtitles(self, url: str, task_id: str) -> Tuple[Path, Optional[Path], Dict[str, Any]]:
        """Download video file (mp4) and best available subtitles (srt/vtt)."""
        task_dir = self.downloads_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        
        out_tmpl = str(task_dir / "%(id)s.%(ext)s")
        
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
            "outtmpl": out_tmpl,
            "quiet": True,
            "writethumbnail": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "srt/vtt/best",
            "subtitleslangs": ["zh", "zh-CN", "zh-TW", "en", "auto"],
            "merge_output_format": "mp4",
            "remote_components": ["ejs:github"],
        }
        cookie_file = self._get_cookie_file()
        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        video_id = info.get("id")
        
        # Locate downloaded video file
        video_file = None
        for ext in ["mp4", "mkv", "webm"]:
            candidate = task_dir / f"{video_id}.{ext}"
            if candidate.exists():
                video_file = candidate
                break

        if not video_file:
            # Fallback to finding any non-subtitle video file in task_dir
            for f in task_dir.iterdir():
                if f.suffix in [".mp4", ".mkv", ".webm"]:
                    video_file = f
                    break
        
        if not video_file:
            raise FileNotFoundError(f"Downloaded video file not found in {task_dir}")

        # Process YouTube cover image thumbnail if downloaded
        import subprocess
        cover_candidates = list(task_dir.glob(f"{video_id}*.jpg")) + list(task_dir.glob(f"{video_id}*.webp")) + list(task_dir.glob(f"{video_id}*.png"))
        cover_out = task_dir / "cover.jpg"
        for candidate in cover_candidates:
            if candidate.exists() and candidate.stat().st_size > 0:
                try:
                    subprocess.run(
                        [
                            "ffmpeg", "-y", "-i", str(candidate),
                            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                            str(cover_out)
                        ],
                        capture_output=True,
                        timeout=15
                    )
                    if cover_out.exists() and cover_out.stat().st_size > 0:
                        logger.info(f"Successfully processed YouTube thumbnail: {cover_out}")
                        break
                except Exception as e:
                    logger.warning(f"Failed converting YouTube thumbnail {candidate}: {e}")

        # Locate subtitle file if available
        sub_file = None
        sub_files = list(task_dir.glob("*.srt")) + list(task_dir.glob("*.vtt"))
        if sub_files:
            # Prefer Chinese, then English, then any
            for f in sub_files:
                if any(k in f.name.lower() for k in ["zh", "cn", "chi"]):
                    sub_file = f
                    break
            if not sub_file:
                sub_file = sub_files[0]

        return video_file, sub_file, info
