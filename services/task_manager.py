import os
import time
import uuid
import json
import logging
import asyncio
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from config import config_manager, BASE_DIR
from services.youtube import YouTubeService
from services.subtitle import SubtitleService
from services.llm import LLMService
from services.bilibili import BilibiliService
from services.cookiecloud import CookieCloudService

logger = logging.getLogger("youtobi.task_manager")
TASKS_FILE = BASE_DIR / "tasks.json"

class Task:
    def __init__(self, task_id: str, youtube_url: str, custom_text: Optional[str] = None, skip_subtitles: bool = False):
        self.id = task_id
        self.youtube_url = youtube_url
        self.custom_text = custom_text
        self.skip_subtitles = skip_subtitles
        self.status = "PENDING"  # PENDING, DOWNLOADING, SUBTITLE_PROCESSING, LLM_REGENERATION, UPLOADING, COMPLETED, FAILED, PAUSED
        self.progress = 0
        self.logs: List[str] = []
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.updated_at = self.created_at
        self.error_message: Optional[str] = None
        
        # Result metadata
        self.youtube_info: Dict[str, Any] = {}
        self.processed_video_path: Optional[str] = None
        self.chinese_srt_path: Optional[str] = None
        self.final_title: str = ""
        self.final_description: str = ""
        self.final_tags: List[str] = []
        self.used_llm: bool = False
        self.bvid: Optional[str] = None
        self.cancelled: bool = False

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs.append(entry)
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[Task {self.id}] {message}")
        if hasattr(self, "_manager") and self._manager:
            self._manager.save_tasks()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "youtube_url": self.youtube_url,
            "custom_text": self.custom_text,
            "skip_subtitles": self.skip_subtitles,
            "status": self.status,
            "progress": self.progress,
            "logs": self.logs,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error_message": self.error_message,
            "youtube_info": self.youtube_info,
            "final_title": self.final_title,
            "final_description": self.final_description,
            "final_tags": self.final_tags,
            "used_llm": self.used_llm,
            "bvid": self.bvid,
            "cancelled": self.cancelled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        task = cls(
            task_id=data["id"],
            youtube_url=data["youtube_url"],
            custom_text=data.get("custom_text"),
            skip_subtitles=data.get("skip_subtitles", False)
        )
        task.status = data.get("status", "PENDING")
        task.progress = data.get("progress", 0)
        task.logs = data.get("logs", [])
        task.created_at = data.get("created_at", task.created_at)
        task.updated_at = data.get("updated_at", task.updated_at)
        task.error_message = data.get("error_message")
        task.youtube_info = data.get("youtube_info", {})
        task.processed_video_path = data.get("processed_video_path")
        task.chinese_srt_path = data.get("chinese_srt_path")
        task.final_title = data.get("final_title", "")
        task.final_description = data.get("final_description", "")
        task.final_tags = data.get("final_tags", [])
        task.used_llm = data.get("used_llm", False)
        task.bvid = data.get("bvid")
        task.cancelled = data.get("cancelled", False)

        return task


class TaskManager:
    def __init__(self, file_path: Path = TASKS_FILE):
        self.file_path = file_path
        self.tasks: Dict[str, Task] = {}
        self.load_tasks()

    def load_tasks(self):
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for task_id, t_dict in data.items():
                        t = Task.from_dict(t_dict)
                        t._manager = self
                        self.tasks[task_id] = t
            except Exception as e:
                logger.error(f"Error loading tasks from {self.file_path}: {e}")


    def save_tasks(self):
        try:
            temp_file = self.file_path.with_suffix(".tmp")
            data = {t_id: t.to_dict() for t_id, t in self.tasks.items()}
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.file_path)
        except Exception as e:
            logger.error(f"Error saving tasks to {self.file_path}: {e}")

    def create_task(self, youtube_url: str, custom_text: Optional[str] = None, skip_subtitles: bool = False) -> Task:
        task_id = str(uuid.uuid4())[:8]
        task = Task(task_id, youtube_url, custom_text, skip_subtitles=skip_subtitles)
        task._manager = self
        self.tasks[task_id] = task
        self.save_tasks()
        
        # Start background processing thread
        thread = threading.Thread(target=self._run_task_pipeline, args=(task,), daemon=True)
        thread.start()
        return task

    def create_batch_tasks(self, items: List[Dict[str, Optional[str]]], skip_subtitles: bool = False) -> List[Task]:
        created = []
        for item in items:
            url = item.get("url")
            custom = item.get("custom_text")
            if url:
                task = self.create_task(url, custom_text=custom, skip_subtitles=skip_subtitles)
                created.append(task)
        return created

    def stop_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        task.cancelled = True
        task.status = "PAUSED"
        task.log("Task was stopped/paused by user.")
        self.save_tasks()
        return True

    def start_task(self, task_id: str) -> Optional[Task]:
        task = self.get_task(task_id)
        if not task:
            return None
        task.cancelled = False
        task.status = "PENDING"
        task.progress = 0
        task.error_message = None
        task.log("Starting/resuming task execution...")
        self.save_tasks()
        thread = threading.Thread(target=self._run_task_pipeline, args=(task,), daemon=True)
        thread.start()
        return task

    def toggle_skip_subtitles(self, task_id: str, skip: Optional[bool] = None) -> Optional[Task]:
        task = self.get_task(task_id)
        if not task:
            return None
        task.skip_subtitles = not task.skip_subtitles if skip is None else skip
        task.log(f"Set task skip_subtitles to {task.skip_subtitles}")
        self.save_tasks()
        return task

    def cancel_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        task.cancelled = True
        task.status = "CANCELLED"
        task.log("Task was cancelled by user.")
        self.save_tasks()
        return True

    def retry_task(self, task_id: str) -> Optional[Task]:
        task = self.get_task(task_id)
        if not task:
            return None
        task.cancelled = False
        task.status = "PENDING"
        task.progress = 0
        task.error_message = None
        task.logs.clear()
        task.log("Retrying task execution...")
        thread = threading.Thread(target=self._run_task_pipeline, args=(task,), daemon=True)
        thread.start()
        return task

    def delete_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        task.cancelled = True
        task.status = "CANCELLED"
        
        # Clean up directory
        cfg = config_manager.all()
        downloads_dir = Path(cfg.get("downloads_dir", "./downloads")) / task_id
        if downloads_dir.exists():
            import shutil
            try:
                shutil.rmtree(downloads_dir)
            except Exception as e:
                logger.warning(f"Error removing directory for task {task_id}: {e}")
                
        self.tasks.pop(task_id, None)
        self.save_tasks()
        return True

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)


    def list_tasks(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in sorted(self.tasks.values(), key=lambda x: x.created_at, reverse=True)]

    def _sync_cookiecloud(self, task: Optional[Task] = None) -> Tuple[Dict[str, str], Optional[str]]:
        """Sync fresh cookies from CookieCloud if configured and update config_manager."""
        cfg = config_manager.all()
        url = str(cfg.get("cookiecloud_url") or "").strip()
        uuid_val = str(cfg.get("cookiecloud_uuid") or "").strip()
        password = str(cfg.get("cookiecloud_password") or "").strip()

        if not url or not uuid_val or not password:
            return {}, None

        try:
            if task:
                task.log("Syncing fresh cookies from CookieCloud before downloading from YouTube...")
            else:
                logger.info("Syncing fresh cookies from CookieCloud...")

            cc_service = CookieCloudService(url, uuid_val, password)
            bili_cookies, yt_netscape = cc_service.fetch_all_synced_cookies()
            update_dict = {}

            if yt_netscape:
                update_dict["youtube_cookies"] = yt_netscape
                if task:
                    task.log("Successfully synced fresh YouTube cookies from CookieCloud!")
                else:
                    logger.info("Successfully synced fresh YouTube cookies from CookieCloud!")

            if bili_cookies:
                if bili_cookies.get("SESSDATA"):
                    update_dict["bilibili_sessdata"] = bili_cookies.get("SESSDATA")
                if bili_cookies.get("bili_jct"):
                    update_dict["bilibili_bili_jct"] = bili_cookies.get("bili_jct")
                if bili_cookies.get("DedeUserID"):
                    update_dict["bilibili_dedeuserid"] = bili_cookies.get("DedeUserID")
                if task:
                    task.log("Successfully synced fresh Bilibili cookies from CookieCloud!")
                else:
                    logger.info("Successfully synced fresh Bilibili cookies from CookieCloud!")

            if update_dict:
                config_manager.update(update_dict)

            return bili_cookies, yt_netscape
        except Exception as e:
            msg = f"CookieCloud cookie sync warning: {e}"
            if task:
                task.log(msg)
            else:
                logger.warning(msg)
            return {}, None

    def _run_task_pipeline(self, task: Task):
        try:
            task.log(f"Starting pipeline for YouTube URL: {task.youtube_url}")

            # Step 0: Sync CookieCloud cookies before downloading from YouTube
            synced_bili_cookies, _ = self._sync_cookiecloud(task=task)

            cfg = config_manager.all()
            downloads_dir = Path(cfg.get("downloads_dir", "./downloads"))
            
            # Step 1: YouTube Extract & Download
            task.status = "DOWNLOADING"
            task.progress = 10
            task.log("Connecting to YouTube and fetching metadata...")
            
            yt_service = YouTubeService(downloads_dir)
            info = yt_service.extract_info(task.youtube_url)
            task.youtube_info = info
            task.log(f"Title: '{info.get('title')}' | Language: {info.get('language') or 'unknown'} | Is Chinese: {info.get('is_chinese')}")

            task.log("Downloading video file and subtitles...")
            video_file, sub_file, _ = yt_service.download_video_and_subtitles(task.youtube_url, task.id)
            task.progress = 35
            task.log(f"Downloaded video file: {video_file.name}")

            if task.cancelled:
                task.log("Pipeline stopped due to cancellation.")
                return

            # Step 2: Subtitle Processing & Burn-in
            task.status = "SUBTITLE_PROCESSING"
            task.progress = 40
            llm_service = LLMService(cfg)
            sub_service = SubtitleService(llm_service)
            
            should_skip_subs = task.skip_subtitles or cfg.get("skip_subtitles", False)

            if should_skip_subs:
                task.log("⚡ Skip Subtitles is ENABLED. Bypassing subtitle STT/translation and FFmpeg burn-in to save CPU resources!")
                processed_video = video_file
                chinese_srt = None
            else:
                is_chinese = info.get("is_chinese", False)
                if not is_chinese:
                    task.log("Video language is NOT Chinese. Generating and burning Chinese subtitles...")
                else:
                    task.log("Video is in Chinese.")

                processed_video, chinese_srt = sub_service.process_subtitles(
                    video_path=video_file,
                    sub_path=sub_file,
                    is_chinese=is_chinese,
                    output_dir=downloads_dir / task.id
                )

            task.processed_video_path = str(processed_video)
            task.chinese_srt_path = str(chinese_srt) if chinese_srt else None
            task.progress = 65
            task.log("Subtitle processing completed.")

            # Step 3: LLM Description Regeneration
            task.status = "LLM_REGENERATION"
            task.progress = 70
            
            llm_enabled = bool(cfg.get("llm_enabled"))
            llm_api_key = str(cfg.get("llm_api_key") or "").strip()

            if llm_enabled:
                if not llm_api_key:
                    task.log("⚠️ LLM AI简介重写已在设置中勾选，但未配置 LLM API Key！已自动回退使用 YouTube 原视频简介文本。请在【设置】中填入 API Key 并保存。")
                else:
                    task.log(f"LLM AI简介已启用 (Model: {cfg.get('llm_model', 'gpt-4o-mini')})。正在调用 AI 生成 B 站标题与简介...")
            else:
                task.log("LLM AI简介未启用。使用 YouTube 原视频标题与简介。")

            llm_result = llm_service.regenerate_description(
                source_title=info.get("title", ""),
                source_description=info.get("description", ""),
                source_language=info.get("language", "en"),
                max_retries=3,
                task_logger=task.log
            )

            task.final_title = llm_result.get("title", info.get("title"))
            base_desc = llm_result.get("description") or info.get("description", "")
            if task.custom_text:
                task.log(f"Applying custom description prefix: '{task.custom_text[:50]}...'")
                task.final_description = f"{task.custom_text}\n\n{base_desc}".strip()
            else:
                task.final_description = base_desc

            task.final_tags = llm_result.get("tags", ["YouTube", "搬运", "视频"])
            task.used_llm = llm_result.get("used_llm", False)
            task.progress = 80
            task.log(f"Final Title: {task.final_title}")
            task.log(f"LLM used: {task.used_llm}")


            # Step 4: Bilibili Upload
            task.status = "UPLOADING"
            task.progress = 85
            task.log("Initiating Bilibili upload service...")
            
            # Sync CookieCloud if configured and not already fetched
            cfg = config_manager.all()
            sessdata = cfg.get("bilibili_sessdata", "")
            bili_jct = cfg.get("bilibili_bili_jct", "")
            dedeuserid = cfg.get("bilibili_dedeuserid", "")

            if not synced_bili_cookies and cfg.get("cookiecloud_url") and cfg.get("cookiecloud_uuid") and cfg.get("cookiecloud_password"):
                synced_bili_cookies, _ = self._sync_cookiecloud(task=task)
                cfg = config_manager.all()
                sessdata = cfg.get("bilibili_sessdata", sessdata)
                bili_jct = cfg.get("bilibili_bili_jct", bili_jct)
                dedeuserid = cfg.get("bilibili_dedeuserid", dedeuserid)

            bili_service = BilibiliService(sessdata, bili_jct, dedeuserid, extra_cookies=synced_bili_cookies or {})
            
            def upload_progress(pct: int, msg: str):
                task.progress = 85 + int(pct * 0.15)
                task.log(msg)

            upload_res = bili_service.upload_video(
                video_path=processed_video,
                title=task.final_title,
                description=task.final_description,
                tags=task.final_tags,
                progress_callback=upload_progress
            )

            task.bvid = upload_res.get("bvid")
            task.status = "COMPLETED"
            task.progress = 100
            task.log(f"🎉 视频已成功同步发布至 Bilibili! BV号: {task.bvid} | 观看链接: https://www.bilibili.com/video/{task.bvid}")

            # Auto cleanup video files after successful upload if enabled
            if cfg.get("auto_delete_after_upload", True):
                try:
                    task_dir = downloads_dir / task.id
                    if task_dir.exists():
                        import shutil
                        shutil.rmtree(task_dir)
                        task.log("Auto-deleted local video files to save disk space after upload.")
                except Exception as clean_err:
                    task.log(f"Warning: Auto-deletion of task video files failed: {clean_err}")

        except Exception as e:
            task.status = "FAILED"
            task.error_message = str(e)
            task.log(f"ERROR: Task failed - {e}")
            logger.error(f"Task {task.id} failed", exc_info=True)

task_manager = TaskManager()
