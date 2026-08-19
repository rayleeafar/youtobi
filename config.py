import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
DOWNLOADS_DIR = BASE_DIR / "downloads"

DEFAULT_CONFIG: Dict[str, Any] = {
    # LLM Configuration
    "llm_enabled": False,
    "llm_provider": "openai",  # openai / deepseek / custom
    "llm_api_key": "",
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-4o-mini",

    # Bilibili Configuration
    "bilibili_sessdata": "",
    "bilibili_bili_jct": "",
    "bilibili_dedeuserid": "",

    # CookieCloud Configuration
    "cookiecloud_url": "",
    "cookiecloud_uuid": "",
    "cookiecloud_password": "",

    # Subtitle Settings
    "subtitle_burn_in": True,
    "subtitle_font_size": 22,

    # FFmpeg Settings
    "ffmpeg_preset": "fast",

    # Whisper STT Configuration
    "whisper_enabled": True,
    "whisper_api_key": "",
    "whisper_base_url": "",
    "whisper_model": "whisper-1",

    # YouTube Settings
    "youtube_cookies": "",

    # Admin Security Settings
    "admin_password": "admin",

    # Upload Targets Configuration (list of "bilibili", "youtube")
    "upload_targets": ["bilibili"],

    # YouTube Upload (Data API v3) Configuration
    "youtube_upload_enabled": False,
    "youtube_client_id": "",
    "youtube_client_secret": "",
    "youtube_refresh_token": "",
    "youtube_privacy_status": "unlisted",  # public / unlisted / private
    "youtube_category_id": "22",  # 22 = People & Blogs, 24 = Entertainment, 27 = Education

    # Video Secondary Creation Engine Settings
    "secondary_creation_enabled": False,
    "secondary_flip_horizontal": False,
    "secondary_border_ratio": 0.0,  # 0.0 to 0.20 (percentage black padding)
    "secondary_watermark_enabled": False,
    "secondary_watermark_text": "",
    "secondary_watermark_opacity": 0.012,

    # Output Settings
    "downloads_dir": str(DOWNLOADS_DIR),
    "auto_delete_after_upload": True,
    "skip_subtitles": False
}

class ConfigManager:
    def __init__(self, file_path: Path = CONFIG_FILE):
        self.file_path = file_path
        self._config = DEFAULT_CONFIG.copy()
        self.load()

    def load(self) -> Dict[str, Any]:
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._config.update(data)
            except Exception as e:
                print(f"[ConfigManager] Error loading config: {e}")
        else:
            self.save()

        # Validate downloads_dir: fall back to BASE_DIR / "downloads" if path is invalid/unwritable or cross-platform mismatch
        d_dir_str = self._config.get("downloads_dir", str(DOWNLOADS_DIR))
        d_dir = Path(d_dir_str)
        is_valid = True
        try:
            d_dir.mkdir(parents=True, exist_ok=True)
            # Test write access
            test_file = d_dir / ".write_test"
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            is_valid = False
            print(f"[ConfigManager] Invalid downloads_dir '{d_dir_str}' ({e}). Falling back to '{DOWNLOADS_DIR}'.")

        if not is_valid:
            self._config["downloads_dir"] = str(DOWNLOADS_DIR)
            DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

        return self._config


    def save(self) -> None:
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ConfigManager] Error saving config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value
        self.save()

    def update(self, new_data: Dict[str, Any]) -> None:
        self._config.update(new_data)
        self.save()

    def all(self) -> Dict[str, Any]:
        return self._config.copy()

config_manager = ConfigManager()
