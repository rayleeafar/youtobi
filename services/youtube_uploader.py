import os
import io
import time
import math
import json
import logging
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
import requests

logger = logging.getLogger("youtobi.youtube_uploader")

YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
YOUTUBE_THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails,statistics&mine=true"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunk size (must be multiple of 256 KB)

class YouTubeUploaderService:
    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        access_token: str = ""
    ):
        self.client_id = client_id.strip() if client_id else ""
        self.client_secret = client_secret.strip() if client_secret else ""
        self.refresh_token = refresh_token.strip() if refresh_token else ""
        self._access_token = access_token.strip() if access_token else ""
        self._token_expiry = 0

    @staticmethod
    def generate_auth_url(client_id: str, redirect_uri: str, state: str = "youtobi_oauth") -> str:
        """Generates Google OAuth2 authorization consent URL."""
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(YOUTUBE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state
        }
        return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    @staticmethod
    def exchange_code_for_tokens(
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str
    ) -> Dict[str, Any]:
        """Exchanges OAuth2 authorization code for refresh and access tokens."""
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri
        }
        resp = requests.post(GOOGLE_TOKEN_URL, data=payload, timeout=20)
        if not resp.ok:
            raise RuntimeError(f"Google OAuth exchange failed ({resp.status_code}): {resp.text}")
        return resp.json()

    def get_access_token(self, force_refresh: bool = False) -> str:
        """Retrieves or refreshes Google OAuth2 access token."""
        now = time.time()
        if self._access_token and not force_refresh and (self._token_expiry == 0 or now < self._token_expiry - 60):
            return self._access_token

        if not self.refresh_token:
            if self._access_token:
                return self._access_token
            raise ValueError("YouTube OAuth2 refresh_token is not configured. Please authorize in Settings.")

        if not self.client_id or not self.client_secret:
            raise ValueError("YouTube client_id or client_secret is missing.")

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }
        resp = requests.post(GOOGLE_TOKEN_URL, data=payload, timeout=20)
        if not resp.ok:
            raise RuntimeError(f"Failed to refresh YouTube OAuth token ({resp.status_code}): {resp.text}")

        data = resp.json()
        self._access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        self._token_expiry = now + int(expires_in)
        return self._access_token

    def get_channel_info(self) -> Dict[str, Any]:
        """Fetches current authorized YouTube channel details."""
        token = self.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(YOUTUBE_CHANNELS_URL, headers=headers, timeout=20)
        if not resp.ok:
            raise RuntimeError(f"Failed to get YouTube channel info ({resp.status_code}): {resp.text}")

        data = resp.json()
        items = data.get("items", [])
        if not items:
            raise RuntimeError("No YouTube channel found associated with this Google account.")

        ch = items[0]
        snippet = ch.get("snippet", {})
        stats = ch.get("statistics", {})
        return {
            "channel_id": ch.get("id"),
            "title": snippet.get("title", "Unknown"),
            "description": snippet.get("description", ""),
            "custom_url": snippet.get("customUrl", ""),
            "subscriber_count": stats.get("subscriberCount", "0"),
            "video_count": stats.get("videoCount", "0"),
            "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", "")
        }

    def _initiate_resumable_upload(
        self,
        file_size: int,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        category_id: str = "22",
        privacy_status: str = "unlisted"
    ) -> str:
        """Starts a resumable upload session and returns upload session URL."""
        token = self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(file_size),
            "X-Upload-Content-Type": "video/mp4"
        }

        # Truncate strings to YouTube constraints
        safe_title = (title or "Untitled")[:100]
        safe_desc = (description or "")[:5000]
        safe_tags = [t[:500] for t in (tags or [])][:50]
        safe_privacy = privacy_status if privacy_status in ["public", "private", "unlisted"] else "unlisted"

        body = {
            "snippet": {
                "title": safe_title,
                "description": safe_desc,
                "tags": safe_tags,
                "categoryId": str(category_id or "22")
            },
            "status": {
                "privacyStatus": safe_privacy,
                "selfDeclaredMadeForKids": False
            }
        }

        resp = requests.post(YOUTUBE_UPLOAD_URL, headers=headers, json=body, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"YouTube initiate resumable upload failed ({resp.status_code}): {resp.text}")

        upload_url = resp.headers.get("Location")
        if not upload_url:
            raise RuntimeError("YouTube API did not return a session upload Location header.")
        return upload_url

    def _upload_chunks(
        self,
        upload_url: str,
        video_path: Path,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """Uploads video file in chunks to YouTube resumable session URL."""
        total_size = video_path.stat().st_size
        if total_size == 0:
            raise ValueError("Video file to upload is empty (0 bytes).")

        num_chunks = math.ceil(total_size / CHUNK_SIZE)
        logger.info(f"Starting YouTube chunked upload for {video_path.name} ({total_size / (1024*1024):.2f} MB, {num_chunks} chunks)...")

        with open(video_path, "rb") as f:
            for chunk_idx in range(num_chunks):
                start_byte = chunk_idx * CHUNK_SIZE
                f.seek(start_byte)
                chunk_data = f.read(CHUNK_SIZE)
                chunk_len = len(chunk_data)
                end_byte = start_byte + chunk_len - 1

                content_range = f"bytes {start_byte}-{end_byte}/{total_size}"
                headers = {
                    "Content-Length": str(chunk_len),
                    "Content-Range": content_range,
                    "Content-Type": "video/mp4"
                }

                pct = int((end_byte + 1) / total_size * 100)
                if progress_callback:
                    progress_callback(pct, f"YouTube uploading chunk {chunk_idx + 1}/{num_chunks} ({pct}%)...")

                retry_attempts = 3
                for attempt in range(retry_attempts):
                    try:
                        resp = requests.put(upload_url, headers=headers, data=chunk_data, timeout=120)
                        if resp.status_code in [200, 201]:
                            # Completed
                            return resp.json()
                        elif resp.status_code == 308:
                            # Resume Incomplete (expected for intermediate chunks)
                            break
                        else:
                            logger.warning(f"YouTube upload chunk {chunk_idx + 1} got status {resp.status_code}: {resp.text[:300]}")
                            if attempt == retry_attempts - 1:
                                raise RuntimeError(f"YouTube chunk upload failed ({resp.status_code}): {resp.text}")
                            time.sleep(2 * (attempt + 1))
                    except requests.RequestException as req_err:
                        logger.warning(f"Network error during YouTube chunk upload attempt {attempt + 1}: {req_err}")
                        if attempt == retry_attempts - 1:
                            raise
                        time.sleep(3 * (attempt + 1))

        raise RuntimeError("YouTube upload ended without receiving completion response.")

    def set_thumbnail(self, video_id: str, cover_path: Path) -> bool:
        """Uploads custom thumbnail image for a video."""
        cover_path = Path(cover_path)
        if not cover_path.exists() or cover_path.stat().st_size == 0:
            return False

        try:
            token = self.get_access_token()
            url = f"{YOUTUBE_THUMBNAIL_URL}?videoId={video_id}"
            content_type = "image/png" if cover_path.suffix.lower() == ".png" else "image/jpeg"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type
            }
            with open(cover_path, "rb") as f:
                resp = requests.post(url, headers=headers, data=f.read(), timeout=30)
            if resp.ok:
                logger.info(f"Successfully uploaded YouTube thumbnail for video {video_id}")
                return True
            else:
                logger.warning(f"Failed setting YouTube thumbnail ({resp.status_code}): {resp.text[:300]}")
                return False
        except Exception as e:
            logger.warning(f"Error setting YouTube thumbnail: {e}")
            return False

    def upload_video(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        category_id: str = "22",
        privacy_status: str = "unlisted",
        cover_path: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Orchestrates full YouTube video upload pipeline:
        1. Initialize resumable session.
        2. Stream chunks with progress reporting.
        3. Upload thumbnail cover image if available.
        4. Return video metadata and watch URL.
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found for upload: {video_path}")

        file_size = video_path.stat().st_size

        if progress_callback:
            progress_callback(5, "Initializing YouTube Resumable Upload session...")

        upload_url = self._initiate_resumable_upload(
            file_size=file_size,
            title=title,
            description=description,
            tags=tags,
            category_id=category_id,
            privacy_status=privacy_status
        )

        upload_res = self._upload_chunks(
            upload_url=upload_url,
            video_path=video_path,
            progress_callback=progress_callback
        )

        video_id = upload_res.get("id")
        if not video_id:
            raise RuntimeError(f"YouTube upload succeeded but no video id in response: {upload_res}")

        yt_watch_url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"YouTube video successfully uploaded! Video ID: {video_id} | Link: {yt_watch_url}")

        if cover_path and Path(cover_path).exists():
            if progress_callback:
                progress_callback(95, "Uploading YouTube custom thumbnail...")
            self.set_thumbnail(video_id, cover_path)

        if progress_callback:
            progress_callback(100, f"YouTube upload completed! Watch URL: {yt_watch_url}")

        return {
            "video_id": video_id,
            "url": yt_watch_url,
            "title": title,
            "privacy_status": privacy_status,
            "raw_response": upload_res
        }
