import os
import time
import math
import json
import logging
import subprocess
import shutil
import tempfile
import re
import asyncio
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List
import requests

logger = logging.getLogger("youtobi.bilibili")


class BilibiliService:
    def __init__(self, sessdata: str = "", bili_jct: str = "", dedeuserid: str = "", extra_cookies: Optional[Dict[str, str]] = None):
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.dedeuserid = dedeuserid
        self.extra_cookies = extra_cookies or {}

    @staticmethod
    def get_video_duration(video_path: Path) -> float:
        """Gets exact duration of video file in seconds using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and res.stdout.strip():
                return float(res.stdout.strip())
        except Exception as e:
            logger.warning(f"Error getting video duration: {e}")
        return 0.0

    @staticmethod
    def split_video_if_needed(video_path: Path, max_duration_sec: int = 28800) -> List[Path]:
        """
        If video duration exceeds max_duration_sec (default 8 hours / 28,800 sec),
        splits the video into multiple part files (e.g. part_P1.mp4, part_P2.mp4...)
        using ffmpeg stream copy (-c copy) without re-encoding.
        Returns list of video part file paths.
        """
        video_path = Path(video_path)
        duration = BilibiliService.get_video_duration(video_path)
        
        if duration <= max_duration_sec or duration == 0.0:
            return [video_path]
        
        parts_dir = video_path.parent / f"{video_path.stem}_parts"
        parts_dir.mkdir(parents=True, exist_ok=True)

        num_parts = math.ceil(duration / max_duration_sec)
        logger.info(f"Video duration is {duration:.1f}s ({duration/3600:.2f} hours), which exceeds Bilibili max limit of {max_duration_sec/3600:.1f} hours.")
        logger.info(f"Splitting video into {num_parts} parts using ffmpeg (-c copy)...")

        split_files: List[Path] = []
        for i in range(num_parts):
            start_time = i * max_duration_sec
            part_file = parts_dir / f"{video_path.stem}_P{i+1}{video_path.suffix}"
            
            if part_file.exists() and part_file.stat().st_size > 1000000:
                logger.info(f"Reusing existing split Part {i+1}/{num_parts}: {part_file.name} ({part_file.stat().st_size / (1024*1024):.1f} MB)")
                split_files.append(part_file)
                continue

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-i", str(video_path),
                "-t", str(max_duration_sec),
                "-c", "copy",
                str(part_file)
            ]
            
            logger.info(f"Splitting Part {i+1}/{num_parts}: start={start_time}s, duration={max_duration_sec}s -> {part_file.name}")
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and part_file.exists() and part_file.stat().st_size > 0:
                split_files.append(part_file)
            else:
                logger.error(f"FFmpeg split failed for Part {i+1}: {res.stderr[:300]}")
                return [video_path]


        if len(split_files) == num_parts:
            logger.info(f"Successfully split video into {len(split_files)} parts for Multi-P upload!")
            return split_files
        return [video_path]

    def get_cookies(self) -> Dict[str, str]:
        cookies = {
            "SESSDATA": self.sessdata,
            "bili_jct": self.bili_jct,
            "DedeUserID": self.dedeuserid,
        }
        cookies.update(self.extra_cookies)
        return cookies

    def validate_credentials(self) -> Dict[str, Any]:
        """Validates if current SESSDATA cookie is logged in to Bilibili."""
        if not self.sessdata:
            return {"valid": False, "message": "SESSDATA cookie is empty."}
        
        url = "https://api.bilibili.com/x/web-interface/nav"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/"
        }
        try:
            res = requests.get(url, cookies=self.get_cookies(), headers=headers, timeout=10)
            data = res.json()
            if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
                user_info = data.get("data", {})
                return {
                    "valid": True,
                    "uname": user_info.get("uname"),
                    "mid": user_info.get("mid"),
                    "face": user_info.get("face"),
                    "level": user_info.get("level_info", {}).get("current_level"),
                }
            else:
                return {"valid": False, "message": data.get("message", "Cookie is invalid or expired.")}
        except Exception as e:
            return {"valid": False, "message": f"Network error during verification: {e}"}

    @staticmethod
    def _ensure_cover_image(video_parts: List[Path]) -> Path:
        """
        Guarantees a valid 16:9 cover image exists on disk.
        Tier 1: YouTube thumbnail (cover.jpg, *.jpg, *.webp, *.png) in parent dir.
        Tier 2: Extract frame at 5 seconds into video stream.
        Tier 3: Solid color 1280x720 fallback image.
        """
        first_part = video_parts[0]
        parent_dir = first_part.parent
        cover_out = parent_dir / "cover.jpg"

        if cover_out.exists() and cover_out.stat().st_size > 0:
            return cover_out

        existing_images = list(parent_dir.glob("*.jpg")) + list(parent_dir.glob("*.webp")) + list(parent_dir.glob("*.png"))
        for img in existing_images:
            if img.exists() and img.stat().st_size > 0 and img.name != "cover.jpg":
                try:
                    subprocess.run(
                        [
                            "ffmpeg", "-y", "-i", str(img),
                            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                            str(cover_out)
                        ],
                        capture_output=True,
                        timeout=15
                    )
                    if cover_out.exists() and cover_out.stat().st_size > 0:
                        logger.info(f"Converted YouTube thumbnail {img.name} -> cover.jpg")
                        return cover_out
                except Exception as e:
                    logger.warning(f"Error converting image {img}: {e}")

        # Tier 2: Extract frame from 5 seconds into video stream
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", "00:00:05", "-i", str(first_part),
                    "-vframes", "1",
                    "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                    str(cover_out)
                ],
                capture_output=True,
                timeout=15
            )
            if cover_out.exists() and cover_out.stat().st_size > 0:
                logger.info("Successfully extracted video frame at 5s -> cover.jpg")
                return cover_out
        except Exception as e:
            logger.warning(f"Failed extracting video frame at 5s: {e}")

        # Try 1s if 5s failed
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", "00:00:01", "-i", str(first_part),
                    "-vframes", "1",
                    "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                    str(cover_out)
                ],
                capture_output=True,
                timeout=15
            )
            if cover_out.exists() and cover_out.stat().st_size > 0:
                logger.info("Successfully extracted video frame at 1s -> cover.jpg")
                return cover_out
        except Exception as e:
            logger.warning(f"Failed extracting video frame at 1s: {e}")

        # Tier 3: Solid color fallback image
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1280x720:d=1",
                    "-vframes", "1", str(cover_out)
                ],
                capture_output=True,
                timeout=10
            )
            logger.info("Generated solid fallback cover -> cover.jpg")
        except Exception as e:
            logger.error(f"Failed generating solid cover fallback: {e}")

        return cover_out

    def upload_video(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: List[str],
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Uploads video to Bilibili using biliup engine / Web Upload API.
        Automatically splits videos longer than 8 hours into Multi-P parts.
        """
        title = title[:80]
        description = description[:2000]
        video_path = Path(video_path)

        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Check and split video if duration > 8 hours (28,800 seconds)
        video_parts = BilibiliService.split_video_if_needed(video_path, max_duration_sec=28800)
        is_multi_p = len(video_parts) > 1

        if is_multi_p and progress_callback:
            progress_callback(5, f"Video duration > 8h. Split into {len(video_parts)} parts for Multi-P upload.")

        if progress_callback:
            progress_callback(10, "Initializing Bilibili upload session...")

        # If credentials are not provided, simulate upload step safely for dry-run
        if not self.sessdata:
            logger.warning("No Bilibili SESSDATA provided. Performing dry-run upload check.")
            for p in range(20, 100, 20):
                time.sleep(0.5)
                if progress_callback:
                    progress_callback(p, f"Dry-run upload progress: {p}%")
            return {
                "success": True,
                "bvid": "BV_DRY_RUN_DEMO",
                "message": "Dry-run completed successfully (Credentials not configured).",
                "title": title,
                "description": description,
                "tags": tags
            }

        # Pre-flight credential check
        cred_check = self.validate_credentials()
        if not cred_check.get("valid"):
            err_reason = cred_check.get("message", "账号未登录")
            raise RuntimeError(
                f"Bilibili 登录凭据无效或已失效 ({err_reason})，无法上传视频。"
                f"请在浏览器中重新登录 B站 并通过 CookieCloud 同步，或在设置中更新 SESSDATA！"
            )
        logger.info(f"Bilibili credentials verified for user '{cred_check.get('uname')}' (UID: {cred_check.get('mid')})")

        # Method A: Try bilibili-api-python UPOS uploader engine
        try:
            import asyncio
            from bilibili_api import Credential, video_uploader

            if progress_callback:
                progress_callback(20, f"Preparing bilibili-api-python UPOS engine ({len(video_parts)} parts)...")

            buivid3 = self.extra_cookies.get("buivid3", "")
            buivid4 = self.extra_cookies.get("buivid4", "")
            if not buivid3:
                try:
                    r_spi = requests.get('https://api.bilibili.com/x/frontend/finger/spi', headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                    spi_data = r_spi.json().get('data', {})
                    buivid3 = spi_data.get('b_3', '')
                    buivid4 = spi_data.get('b_4', '')
                except Exception as e:
                    logger.warning(f"Could not fetch SPI finger: {e}")

            cred = Credential(
                sessdata=self.sessdata,
                bili_jct=self.bili_jct,
                dedeuserid=self.dedeuserid,
                buivid3=buivid3,
                buivid4=buivid4
            )

            cover_path = self._ensure_cover_image(video_parts)

            pages = []
            for idx, part_p in enumerate(video_parts, start=1):
                p_title = f"P{idx} {title[:70]}" if is_multi_p else title[:80]
                pages.append(video_uploader.VideoUploaderPage(
                    path=str(part_p),
                    title=p_title
                ))

            meta = video_uploader.VideoMeta(
                title=title[:80],
                desc=description[:2000],
                cover=str(cover_path),
                tid=21,
                tags=tags[:12],
                original=False,
                source="https://youtube.com"
            )

            uploader = video_uploader.VideoUploader(pages=pages, meta=meta, credential=cred)

            if progress_callback:
                @uploader.on('progress')
                def on_progress(p):
                    try:
                        pct = 20 + int(float(p) * 0.75)
                        progress_callback(min(95, pct), f"UPOS upload progress: {p}%")
                    except Exception:
                        pass

            async def _do_upload():
                return await uploader.start()

            res = asyncio.run(_do_upload())
            bvid = res.get("bvid", "BV_SUCCESS")
            if progress_callback:
                progress_callback(100, f"Successfully published video ({len(video_parts)} parts) to Bilibili! BVid: {bvid}")

            return {
                "success": True,
                "bvid": bvid,
                "title": title,
                "description": description,
                "tags": tags
            }
        except Exception as e:
            logger.warning(f"bilibili-api-python engine failed: {e}. Trying biliup fallback...")

        # Method B: Try biliup CLI engine if available
        biliup_path = shutil.which("bilibili") or shutil.which("biliup")

        if not biliup_path:
            venv_biliup = Path(__file__).resolve().parent.parent / "venv" / "bin" / "biliup"
            if venv_biliup.exists():
                biliup_path = str(venv_biliup)

        if biliup_path:
            try:
                if progress_callback:
                    progress_callback(20, "Preparing biliup engine & cookie credentials...")

                mid_int = int(self.dedeuserid) if self.dedeuserid and self.dedeuserid.isdigit() else 0
                u32_expires = 2147483647  # Max signed 32-bit int to prevent Rust u32 overflow
                
                # Format all extra cookies into biliup cookie format
                cookie_items = [
                    {"name": "SESSDATA", "value": self.sessdata, "expires": u32_expires, "http_only": False, "secure": False},
                    {"name": "bili_jct", "value": self.bili_jct, "expires": u32_expires, "http_only": False, "secure": False},
                    {"name": "DedeUserID", "value": self.dedeuserid, "expires": u32_expires, "http_only": False, "secure": False},
                ]
                for k, v in self.extra_cookies.items():
                    if k not in ["SESSDATA", "bili_jct", "DedeUserID"]:
                        cookie_items.append({"name": k, "value": str(v), "expires": u32_expires, "http_only": False, "secure": False})

                bili_cookies_format = {
                    "cookie_info": {
                        "cookies": cookie_items,
                        "domains": [".bilibili.com", "bilibili.com"]
                    },
                    "token_info": {
                        "mid": mid_int,
                        "access_token": "",
                        "refresh_token": "",
                        "expires_in": u32_expires
                    },
                    "sso": []
                }

                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
                    json.dump(bili_cookies_format, tf)
                    cookie_file_path = tf.name

                try:
                    if progress_callback:
                        progress_callback(40, f"Uploading video binary ({len(video_parts)} parts) via high-speed UPOS engine...")

                    cover_path = self._ensure_cover_image(video_parts)
                    cmd = [
                        biliup_path,
                        "-u", cookie_file_path,
                        "upload",
                        "--submit", "b-cut-android",
                        "--copyright", "2",
                        "--cover", str(cover_path),
                        "--source", "https://youtube.com",
                        "--tid", "21",
                        "--title", title,
                        "--desc", description,
                        "--tag", ",".join(tags[:12]),
                    ] + [str(p) for p in video_parts]

                    logger.info(f"Executing biliup command: {' '.join(cmd[:7])} ...")
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1
                    )

                    output_lines = []
                    for line in proc.stdout:
                        clean_line = line.strip()
                        output_lines.append(clean_line)
                        if "upload" in clean_line.lower() or "progress" in clean_line.lower() or "submit" in clean_line.lower():
                            if progress_callback:
                                progress_callback(75, f"biliup: {clean_line[:80]}")
                        logger.info(f"[biliup] {clean_line}")

                    proc.wait()

                    full_output = "\n".join(output_lines)
                    if proc.returncode == 0:
                        bvid = "BV_SUCCESS"
                        bv_match = re.search(r"(BV[a-zA-Z0-9]{10})", full_output)
                        if bv_match:
                            bvid = bv_match.group(1)

                        if progress_callback:
                            progress_callback(100, f"Successfully published video ({len(video_parts)} parts) to Bilibili! BVid: {bvid}")

                        return {
                            "success": True,
                            "bvid": bvid,
                            "title": title,
                            "description": description,
                            "tags": tags
                        }
                    else:
                        logger.warning(f"biliup exited with code {proc.returncode}. Output: {full_output[:500]}")
                finally:
                    if os.path.exists(cookie_file_path):
                        os.remove(cookie_file_path)
            except Exception as e:
                logger.warning(f"biliup engine failed: {e}. Falling back to Web API...")

        # Method C: Web API fallback with robust multi-part support & SPI finger cookies
        try:
            buivid3 = self.extra_cookies.get("buivid3", "")
            buivid4 = self.extra_cookies.get("buivid4", "")
            if not buivid3:
                try:
                    r_spi = requests.get('https://api.bilibili.com/x/frontend/finger/spi', headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                    spi_data = r_spi.json().get('data', {})
                    buivid3 = spi_data.get('b_3', '')
                    buivid4 = spi_data.get('b_4', '')
                except Exception:
                    pass

            cookie_str = f"SESSDATA={self.sessdata}; bili_jct={self.bili_jct}; DedeUserID={self.dedeuserid}"
            if buivid3:
                cookie_str += f"; buivid3={buivid3}"
            if buivid4:
                cookie_str += f"; buivid4={buivid4}"

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://member.bilibili.com/platform/upload-v2/video",
                "Cookie": cookie_str
            }


            uploaded_videos = []


            for idx, part_p in enumerate(video_parts, start=1):
                p_title = f"P{idx} {title[:70]}" if is_multi_p else title[:80]
                if progress_callback:
                    progress_callback(40 + int(idx / len(video_parts) * 40), f"Uploading part {idx}/{len(video_parts)} ({part_p.name}) to Bilibili UPOS...")

                encoded_name = urllib.parse.quote(part_p.name)
                preupload_url = f"https://member.bilibili.com/preupload?name={encoded_name}&size={part_p.stat().st_size}&r=upos&profile=ugc%2Fpc&ssl=0"
                
                r_pre = requests.get(preupload_url, headers=headers, timeout=15)
                if r_pre.status_code != 200:
                    if "<!DOCTYPE" in r_pre.text or "<html" in r_pre.text or "出错啦" in r_pre.text:
                        err_detail = "Bilibili 会话验证失败 (HTTP 403 出错啦/未登录页面)，请确认 SESSDATA 有效性"
                    else:
                        err_detail = r_pre.text[:200]
                    raise RuntimeError(f"Bilibili preupload HTTP {r_pre.status_code}: {err_detail}")
                
                try:
                    pre_data = r_pre.json()
                except Exception:
                    raise RuntimeError(f"Bilibili preupload invalid response (HTTP {r_pre.status_code}): {r_pre.text[:200]}")

                filename = pre_data.get("filename", "")
                endpoint = pre_data.get("endpoint", "")
                upos_uri = pre_data.get("upos_uri", "")
                auth = pre_data.get("auth", "")

                if not filename or not endpoint:
                    raise RuntimeError(f"Bilibili preupload missing upload params: {pre_data}")

                upload_url = f"https:{endpoint}/{upos_uri.replace('upos://', '')}?output=json"
                upload_headers = headers.copy()
                upload_headers["X-Upos-Auth"] = auth
                
                with open(part_p, "rb") as f:
                    r_up = requests.put(upload_url, data=f, headers=upload_headers, timeout=300)

                if r_up.status_code not in (200, 201):
                    raise RuntimeError(f"UPOS upload HTTP {r_up.status_code}: {r_up.text[:200]}")

                uploaded_videos.append({
                    "title": p_title,
                    "filename": filename,
                    "desc": ""
                })

            if progress_callback:
                progress_callback(85, "Submitting video metadata to Bilibili member center...")

            add_url = f"https://member.bilibili.com/x/vu/web/add/v3?csrf={self.bili_jct}"
            payload = {
                "copyright": 2,
                "source": "https://youtube.com",
                "title": title,
                "tid": 21,
                "tag": ",".join(tags[:12]),
                "desc": description,
                "videos": uploaded_videos,
                "csrf": self.bili_jct
            }

            r_add = requests.post(add_url, json=payload, headers=headers, timeout=15)
            if r_add.status_code != 200:
                raise RuntimeError(f"Bilibili submit HTTP {r_add.status_code}: {r_add.text[:200]}")

            try:
                res_json = r_add.json()
            except Exception:
                raise RuntimeError(f"Bilibili submit invalid response (HTTP {r_add.status_code}): {r_add.text[:200]}")

            if res_json.get("code") == 0:
                bvid = res_json.get("data", {}).get("bvid", "BV_SUCCESS")
                if progress_callback:
                    progress_callback(100, f"Successfully published video ({len(video_parts)} parts) to Bilibili!")
                return {
                    "success": True,
                    "bvid": bvid,
                    "title": title,
                    "description": description,
                    "tags": tags
                }
            else:
                msg = res_json.get("message", "Failed to submit video metadata.")
                raise RuntimeError(f"Bilibili API error ({res_json.get('code')}): {msg}")

        except Exception as e:
            logger.error(f"Bilibili upload error: {e}")
            raise RuntimeError(f"Upload failed: {e}")

