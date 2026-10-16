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
            if not isinstance(data, dict):
                return {"valid": False, "message": "Invalid response format from Bilibili API."}
            data_body = data.get("data") or {}
            if data.get("code") == 0 and isinstance(data_body, dict) and data_body.get("isLogin"):
                level_info = data_body.get("level_info") or {}
                return {
                    "valid": True,
                    "uname": data_body.get("uname"),
                    "mid": data_body.get("mid"),
                    "face": data_body.get("face"),
                    "level": level_info.get("current_level") if isinstance(level_info, dict) else None,
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

            extra = self.extra_cookies or {}
            buvid3 = extra.get("buvid3") or extra.get("buivid3", "")
            buvid4 = extra.get("buvid4") or extra.get("buivid4", "")
            if not buvid3:
                try:
                    r_spi = requests.get('https://api.bilibili.com/x/frontend/finger/spi', headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                    spi_json = r_spi.json()
                    spi_data = (spi_json.get('data') or {}) if isinstance(spi_json, dict) else {}
                    buvid3 = spi_data.get('b_3', '')
                    buvid4 = spi_data.get('b_4', '')
                except Exception as e:
                    logger.warning(f"Could not fetch SPI finger: {e}")

            cred = Credential(
                sessdata=self.sessdata,
                bili_jct=self.bili_jct,
                dedeuserid=self.dedeuserid,
                buvid3=buvid3,
                buvid4=buvid4
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
            bvid = (res.get("bvid") if isinstance(res, dict) else None) or "BV_SUCCESS"
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

        if not biliup_path:
            for p in ["/usr/local/bin/biliup", "/usr/bin/biliup", "/home/ray/.cargo/bin/biliup"]:
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    biliup_path = p
                    break

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
            extra = self.extra_cookies or {}
            buvid3 = extra.get("buvid3") or extra.get("buivid3", "")
            buvid4 = extra.get("buvid4") or extra.get("buivid4", "")
            if not buvid3:
                try:
                    r_spi = requests.get('https://api.bilibili.com/x/frontend/finger/spi', headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                    spi_json = r_spi.json()
                    spi_data = (spi_json.get('data') or {}) if isinstance(spi_json, dict) else {}
                    buvid3 = spi_data.get('b_3', '')
                    buvid4 = spi_data.get('b_4', '')
                except Exception:
                    pass

            cookie_dict = {"SESSDATA": self.sessdata, "bili_jct": self.bili_jct, "DedeUserID": self.dedeuserid}
            if self.extra_cookies:
                cookie_dict.update(self.extra_cookies)
            if buvid3 and "buvid3" not in cookie_dict:
                cookie_dict["buvid3"] = buvid3
            if buvid4 and "buvid4" not in cookie_dict:
                cookie_dict["buvid4"] = buvid4

            cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_dict.items() if v])

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

            if isinstance(res_json, dict) and res_json.get("code") == 0:
                res_data = res_json.get("data") or {}
                bvid = res_data.get("bvid", "BV_SUCCESS") if isinstance(res_data, dict) else "BV_SUCCESS"
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
                msg = res_json.get("message", "Failed to submit video metadata.") if isinstance(res_json, dict) else "Failed to submit video metadata."
                code = res_json.get('code') if isinstance(res_json, dict) else -1
                raise RuntimeError(f"Bilibili API error ({code}): {msg}")

        except Exception as e:
            logger.error(f"Bilibili upload error: {e}")
            raise RuntimeError(f"Upload failed: {e}")

    def list_seasons(self, pn: int = 1, ps: int = 50) -> Dict[str, Any]:
        """
        Fetches list of video seasons (合集) for the authenticated Bilibili user.
        Primary: member creative center API.
        Fallback: bilibili_api user channel list if applicable.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://member.bilibili.com/platform/upload-manager/season",
        }
        url = f"https://member.bilibili.com/x2/creative/web/seasons?pn={pn}&ps={ps}&order=mtime&sort=desc&draft=1"
        try:
            res = requests.get(url, cookies=self.get_cookies(), headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and data.get("code") == 0:
                    d_body = data.get("data") or {}
                    items = []
                    if isinstance(d_body, dict):
                        raw_items = d_body.get("items") or d_body.get("seasons") or []
                        total = (d_body.get("page") or {}).get("total", len(raw_items))
                        for it in raw_items:
                            if not isinstance(it, dict):
                                continue
                            sec_id = None
                            sections = it.get("sections") or []
                            if sections and isinstance(sections, list) and isinstance(sections[0], dict):
                                sec_id = sections[0].get("id") or sections[0].get("section_id")
                            elif it.get("section_id"):
                                sec_id = it.get("section_id")
                            
                            items.append({
                                "id": it.get("id") or it.get("season_id"),
                                "title": it.get("title", ""),
                                "cover": it.get("cover", ""),
                                "desc": it.get("desc", ""),
                                "ep_count": it.get("ep_count", it.get("total", 0)),
                                "section_id": sec_id,
                                "mtime": it.get("mtime", it.get("ctime", 0)),
                            })
                        return {"seasons": items, "total": total}
        except Exception as e:
            logger.warning(f"Error fetching seasons from creative center: {e}")

        # Fallback to bilibili_api if dedeuserid is present
        if self.dedeuserid:
            try:
                from bilibili_api import user, Credential
                cred = Credential(sessdata=self.sessdata, bili_jct=self.bili_jct, dedeuserid=self.dedeuserid)
                u = user.User(int(self.dedeuserid), credential=cred)
                ch_list = asyncio.run(u.get_channel_series_and_spec_list())
                series_list = []
                if isinstance(ch_list, dict):
                    raw_series = (ch_list.get("series_list") or {}).get("series_list") or []
                    for s in raw_series:
                        meta = s.get("meta") or {}
                        series_list.append({
                            "id": meta.get("series_id"),
                            "title": meta.get("name", ""),
                            "cover": meta.get("cover", ""),
                            "desc": meta.get("description", ""),
                            "ep_count": meta.get("total", 0),
                            "section_id": None,
                            "mtime": meta.get("mtime", 0),
                        })
                return {"seasons": series_list, "total": len(series_list)}
            except Exception as e2:
                logger.warning(f"Fallback bilibili_api seasons lookup failed: {e2}")

        return {"seasons": [], "total": 0}

    def create_season(self, title: str, desc: str = "", cover: str = "") -> Dict[str, Any]:
        """
        Creates a new season/series (合集) in Bilibili member creative center.
        """
        title = title.strip()[:40]
        if not title:
            raise ValueError("Season title cannot be empty")
        
        url = f"https://member.bilibili.com/x2/creative/web/season/add?csrf={self.bili_jct}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://member.bilibili.com/platform/upload-manager/season",
        }
        payload = {
            "title": title,
            "desc": desc[:200] if desc else "",
            "cover": cover or "",
            "csrf": self.bili_jct,
        }
        res = requests.post(url, data=payload, cookies=self.get_cookies(), headers=headers, timeout=15)
        if res.status_code != 200:
            raise RuntimeError(f"Bilibili create season HTTP {res.status_code}: {res.text[:200]}")
        data = res.json()
        if not isinstance(data, dict) or data.get("code") != 0:
            msg = data.get("message", "Failed to create season") if isinstance(data, dict) else "Unknown error"
            code = data.get("code", -1) if isinstance(data, dict) else -1
            raise RuntimeError(f"Bilibili create season error ({code}): {msg}")
        
        res_data = data.get("data") or {}
        season_id = res_data.get("season_id") or res_data.get("id")
        section_id = res_data.get("section_id")
        return {
            "success": True,
            "season_id": season_id,
            "section_id": section_id,
            "title": title,
        }

    def get_season_section(self, season_id: int) -> Optional[int]:
        """
        Finds the default section_id for a given season_id.
        """
        res = self.list_seasons(pn=1, ps=50)
        for s in res.get("seasons", []):
            if s.get("id") == season_id and s.get("section_id"):
                return s["section_id"]
        
        url = f"https://member.bilibili.com/x2/creative/web/season/section/list?season_id={season_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://member.bilibili.com/platform/upload-manager/season",
        }
        try:
            r = requests.get(url, cookies=self.get_cookies(), headers=headers, timeout=10)
            if r.status_code == 200:
                d = r.json()
                if isinstance(d, dict) and d.get("code") == 0:
                    sections = d.get("data") or []
                    if isinstance(sections, list) and sections:
                        return sections[0].get("id") or sections[0].get("section_id")
        except Exception as e:
            logger.warning(f"Error getting season section list: {e}")
        return None

    def add_to_season(self, season_id: int, bvid: str, section_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Adds a published video (bvid) into a season (合集).
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://member.bilibili.com/platform/upload-manager/season",
        }

        # Step 1: Query aid, cid, and title of the video
        view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        r_view = requests.get(view_url, cookies=self.get_cookies(), headers=headers, timeout=12)
        if r_view.status_code != 200:
            raise RuntimeError(f"Failed to fetch video details for {bvid}: HTTP {r_view.status_code}")
        view_data = r_view.json()
        if not isinstance(view_data, dict) or view_data.get("code") != 0:
            msg = view_data.get("message", "Failed to get video info") if isinstance(view_data, dict) else "Unknown"
            raise RuntimeError(f"Failed to fetch video details for {bvid}: {msg}")
        
        v_info = view_data.get("data") or {}
        aid = v_info.get("aid")
        cid = v_info.get("cid")
        ep_title = v_info.get("title", "")
        if not aid or not cid:
            raise RuntimeError(f"Missing aid/cid in video info for {bvid}: aid={aid}, cid={cid}")

        # Step 2: Determine section_id if not provided
        if not section_id:
            section_id = self.get_season_section(season_id)
            if not section_id:
                logger.warning(f"Could not determine section_id for season {season_id}, using season_id as section_id")
                section_id = season_id

        # Step 3: Append video episode to season section
        add_url = f"https://member.bilibili.com/x2/creative/web/season/section/episodes/add?csrf={self.bili_jct}"
        payload = {
            "sectionId": section_id,
            "episodes": [
                {
                    "aid": aid,
                    "cid": cid,
                    "title": ep_title[:80],
                    "charging_pay": 0
                }
            ],
            "csrf": self.bili_jct
        }
        res = requests.post(add_url, json=payload, cookies=self.get_cookies(), headers=headers, timeout=15)
        if res.status_code != 200:
            raise RuntimeError(f"Bilibili add to season HTTP {res.status_code}: {res.text[:200]}")
        data = res.json()
        if not isinstance(data, dict) or data.get("code") != 0:
            msg = data.get("message", "Failed to add episode to season") if isinstance(data, dict) else "Unknown error"
            code = data.get("code", -1) if isinstance(data, dict) else -1
            raise RuntimeError(f"Bilibili add to season error ({code}): {msg}")

        return {
            "success": True,
            "season_id": season_id,
            "section_id": section_id,
            "bvid": bvid,
            "aid": aid,
            "cid": cid,
            "title": ep_title
        }

    def get_or_create_season(self, title: str, desc: str = "", cover: str = "") -> Dict[str, Any]:
        """
        Retrieves existing season with matching title, or creates a new one.
        Prevents redundant season creation.
        """
        clean_title = title.strip()
        existing = self.list_seasons(pn=1, ps=50)
        for s in existing.get("seasons", []):
            if s.get("title", "").strip().lower() == clean_title.lower():
                return {
                    "success": True,
                    "season_id": s["id"],
                    "section_id": s.get("section_id"),
                    "title": s["title"],
                    "reused": True,
                }
        
        created = self.create_season(title=clean_title, desc=desc, cover=cover)
        created["reused"] = False
        return created


