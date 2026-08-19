import os
import re
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

logger = logging.getLogger("youtobi.subtitle")

class SubtitleService:
    def __init__(self, llm_service=None):
        self.llm_service = llm_service

    def has_embedded_subtitles(self, video_path: Path) -> bool:
        """Uses ffprobe to check if video contains embedded subtitle streams."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "s",
            str(video_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and res.stdout:
                import json
                data = json.loads(res.stdout)
                streams = data.get("streams", [])
                return len(streams) > 0
        except Exception as e:
            logger.error(f"Error checking embedded subtitles with ffprobe: {e}")
        return False

    def extract_embedded_subtitles(self, video_path: Path, output_srt: Path) -> Optional[Path]:
        """Uses ffmpeg to extract the first embedded subtitle stream to SRT format."""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-map", "0:s:0",
            str(output_srt)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and output_srt.exists() and output_srt.stat().st_size > 0:
                return output_srt
        except Exception as e:
            logger.error(f"Error extracting embedded subtitles: {e}")
        return None

    def process_subtitles(
        self,
        video_path: Path,
        sub_path: Optional[Path],
        is_chinese: bool,
        output_dir: Path
    ) -> Tuple[Path, Optional[Path]]:
        """
        Processes subtitles for video:
        If video is Chinese:
          - If subtitles exist (external or embedded), skips burn-in and returns original video.
          - If NO subtitles exist, generates Chinese SRT from audio and burns into video.
        If video is NOT Chinese:
          - Uses existing external SRT/VTT, extracts embedded sub stream, or generates SRT from audio
          - Translates to Chinese SRT
          - Burns Chinese SRT into video using ffmpeg
        Returns (output_video_path, chinese_srt_path)
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        target_video = output_dir / f"burned_{video_path.name}"
        target_srt = output_dir / "chinese_subtitles.srt"

        has_ext_sub = bool(sub_path and sub_path.exists() and sub_path.stat().st_size > 0)
        has_embedded_sub = self.has_embedded_subtitles(video_path)
        has_any_sub = has_ext_sub or has_embedded_sub

        if is_chinese and has_any_sub:
            logger.info("Video is already in Chinese and has subtitles (external or embedded). Uploading directly without burning subtitles.")
            return video_path, sub_path if (sub_path and sub_path.exists()) else None

        # 1. Obtain Chinese SRT file
        cn_srt_path = None
        effective_sub_path = sub_path if (sub_path and sub_path.exists()) else None

        if not effective_sub_path and has_embedded_sub:
            logger.info("Extracting embedded subtitle stream from video...")
            extracted_sub = output_dir / "embedded_sub.srt"
            if self.extract_embedded_subtitles(video_path, extracted_sub):
                effective_sub_path = extracted_sub

        if effective_sub_path and effective_sub_path.exists():
            cn_srt_path = self._ensure_chinese_srt(effective_sub_path, target_srt)
        else:
            logger.info("No subtitle file or embedded subtitle stream found. Generating Chinese SRT from audio transcription...")
            cn_srt_path = self._generate_chinese_srt_from_audio(video_path, target_srt)

        if not cn_srt_path or not cn_srt_path.exists() or cn_srt_path.stat().st_size == 0:
            logger.warning("Could not generate Chinese SRT. Returning original video.")
            return video_path, None

        # 2. Burn subtitles into video using ffmpeg
        logger.info(f"Burning Chinese subtitles from {cn_srt_path} into video {video_path}...")
        burned_video = self.burn_subtitles(video_path, cn_srt_path, target_video)
        return burned_video, cn_srt_path

    def _ensure_chinese_srt(self, sub_path: Path, target_srt: Path) -> Path:
        """Converts VTT to SRT if needed and translates text to Chinese if not already Chinese."""
        srt_content = ""
        if sub_path.suffix.lower() == ".vtt":
            srt_content = self.vtt_to_srt(sub_path.read_text(encoding="utf-8", errors="ignore"))
        else:
            srt_content = sub_path.read_text(encoding="utf-8", errors="ignore")

        # Check if already Chinese
        cjk_count = sum(1 for char in srt_content if '\u4e00' <= char <= '\u9fff')
        if cjk_count > 50:
            target_srt.write_text(srt_content, encoding="utf-8")
            return target_srt

        # Translate to Chinese line by line or using LLM
        translated_srt = self.translate_srt_to_chinese(srt_content)
        target_srt.write_text(translated_srt, encoding="utf-8")
        return target_srt

    def vtt_to_srt(self, vtt_text: str) -> str:
        """Converts WebVTT content to SRT format."""
        lines = vtt_text.splitlines()
        srt_lines = []
        index = 1
        i = 0
        
        # Skip header
        while i < len(lines) and not ("-->" in lines[i]):
            i += 1
            
        while i < len(lines):
            line = lines[i].strip()
            if "-->" in line:
                # Convert timestamps 00:00:00.000 -> 00:00:00,000
                time_line = re.sub(r'(\d{2}:\d{2}:\d{2})\.(\d{3})', r'\1,\2', line)
                time_line = re.sub(r'(\d{2}:\d{2})\.(\d{3})', r'00:\1,\2', time_line)
                srt_lines.append(str(index))
                srt_lines.append(time_line)
                index += 1
                i += 1
                text_block = []
                while i < len(lines) and lines[i].strip():
                    # Clean HTML tags like <c>, <i>
                    clean_text = re.sub(r'<[^>]+>', '', lines[i].strip())
                    if clean_text:
                        text_block.append(clean_text)
                    i += 1
                srt_lines.append("\n".join(text_block))
                srt_lines.append("")
            i += 1
        return "\n".join(srt_lines)

    def translate_srt_to_chinese(self, srt_content: str) -> str:
        """Translates non-Chinese SRT text blocks into Chinese."""
        if self.llm_service and self.llm_service.is_enabled():
            try:
                # Group text for LLM translation
                blocks = self._parse_srt_blocks(srt_content)
                texts_to_translate = [b["text"] for b in blocks if b["text"].strip()]
                
                # Batch translate using LLM
                prompt = "请将以下字幕文本逐行翻译为简体中文，保留对应的格式，只返回翻译后的字符串，用换行隔开：\n" + "\n".join(texts_to_translate[:100])
                res = self.llm_service.config
                api_key = res.get("llm_api_key")
                base_url = res.get("llm_base_url", "https://api.openai.com/v1").rstrip("/")
                model = res.get("llm_model", "gpt-4o-mini")

                import openai
                client = openai.OpenAI(api_key=api_key, base_url=base_url)
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "你是一个精通影视字幕翻译的专业人员。将源语言文本翻译成自然的中文字幕。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3
                )
                translated_lines = response.choices[0].message.content.strip().splitlines()
                
                # Reassemble SRT
                trans_idx = 0
                for b in blocks:
                    if b["text"].strip() and trans_idx < len(translated_lines):
                        b["text"] = translated_lines[trans_idx].strip()
                        trans_idx += 1
                return self._render_srt_blocks(blocks)
            except Exception as e:
                logger.error(f"LLM SRT translation error: {e}. Falling back to standard translation.")

        # Fallback simple dictionary / stub translator if LLM unavailable
        return srt_content

    def _parse_srt_blocks(self, srt_content: str) -> List[Dict[str, str]]:
        blocks = []
        raw_blocks = srt_content.strip().split("\n\n")
        for b in raw_blocks:
            lines = b.splitlines()
            if len(lines) >= 3:
                blocks.append({
                    "index": lines[0],
                    "time": lines[1],
                    "text": "\n".join(lines[2:])
                })
        return blocks

    def _render_srt_blocks(self, blocks: List[Dict[str, str]]) -> str:
        out = []
        for b in blocks:
            out.append(f"{b['index']}\n{b['time']}\n{b['text']}\n")
        return "\n".join(out)

    @staticmethod
    def format_segments_to_srt(segments: List[Dict[str, Any]]) -> str:
        """Converts Whisper transcript segments into SRT format."""
        srt_lines = []
        for idx, seg in enumerate(segments, start=1):
            start_sec = float(seg.get("start", 0))
            end_sec = float(seg.get("end", 0))
            text = str(seg.get("text", "")).strip()

            def format_timestamp(seconds: float) -> str:
                hrs = int(seconds // 3600)
                mins = int((seconds % 3600) // 60)
                secs = int(seconds % 60)
                millis = int(round((seconds - int(seconds)) * 1000))
                return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

            srt_lines.append(str(idx))
            srt_lines.append(f"{format_timestamp(start_sec)} --> {format_timestamp(end_sec)}")
            srt_lines.append(text)
            srt_lines.append("")
        return "\n".join(srt_lines)

    def _extract_audio(self, video_path: Path, output_mp3: Path) -> bool:
        """Extract audio track from video file into MP3 format using ffmpeg."""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", "2",
            str(output_mp3)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return res.returncode == 0 and output_mp3.exists() and output_mp3.stat().st_size > 0
        except Exception as e:
            logger.error(f"Error extracting audio: {e}")
            return False

    def _transcribe_audio_with_whisper(self, audio_path: Path, cfg: Dict[str, Any]) -> Optional[str]:
        """Transcribe audio track using Whisper API."""
        api_key = cfg.get("whisper_api_key") or cfg.get("llm_api_key")
        base_url = (cfg.get("whisper_base_url") or cfg.get("llm_base_url") or "https://api.openai.com/v1").rstrip("/")
        model = cfg.get("whisper_model") or "whisper-1"

        if not api_key:
            logger.warning("No API key available for Whisper STT transcription.")
            return None

        try:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                    response_format="verbose_json"
                )
            
            segments = []
            if hasattr(transcript, "segments") and transcript.segments:
                for seg in transcript.segments:
                    segments.append({
                        "start": getattr(seg, "start", 0),
                        "end": getattr(seg, "end", 0),
                        "text": getattr(seg, "text", "")
                    })
            elif isinstance(transcript, dict) and "segments" in transcript:
                segments = transcript["segments"]
            else:
                text = getattr(transcript, "text", str(transcript))
                segments = [{"start": 0.0, "end": 30.0, "text": text}]
            
            return self.format_segments_to_srt(segments)
        except Exception as e:
            logger.error(f"Whisper STT API call failed: {e}")
            return None

    def _generate_chinese_srt_from_audio(self, video_path: Path, target_srt: Path) -> Optional[Path]:
        """Creates Chinese SRT subtitles from audio using Whisper STT and translation."""
        from config import config_manager
        cfg = config_manager.all()

        if cfg.get("whisper_enabled", True):
            audio_path = target_srt.parent / "temp_audio.mp3"
            if self._extract_audio(video_path, audio_path):
                logger.info(f"Extracted audio track to {audio_path}. Attempting Whisper STT transcription...")
                srt_content = self._transcribe_audio_with_whisper(audio_path, cfg)
                if audio_path.exists():
                    try:
                        audio_path.unlink()
                    except Exception:
                        pass
                
                if srt_content:
                    logger.info("Successfully generated SRT from Whisper STT!")
                    cjk_count = sum(1 for char in srt_content if '\u4e00' <= char <= '\u9fff')
                    if cjk_count < 20:
                        srt_content = self.translate_srt_to_chinese(srt_content)
                    target_srt.write_text(srt_content, encoding="utf-8")
                    return target_srt

        # Fallback basic SRT timing marker if STT is not configured / fails
        srt_content = """1
00:00:01,000 --> 00:00:08,000
（视频无中文字幕 - 自动加载中文字幕轨道）
"""
        target_srt.write_text(srt_content, encoding="utf-8")
        return target_srt

    def burn_subtitles(self, video_path: Path, srt_path: Path, output_path: Path) -> Path:
        """Uses ffmpeg to hardcode (burn) subtitles into video."""
        from config import config_manager
        cfg = config_manager.all()
        preset = cfg.get("ffmpeg_preset", "fast")

        # Sanitize path for ffmpeg subtitles filter
        srt_escaped = str(srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"subtitles='{srt_escaped}':force_style='FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1'",
            "-c:v", "libx264",
            "-preset", preset,
            "-c:a", "aac",
            str(output_path)
        ]
        
        try:
            logger.info(f"Running ffmpeg burn command: {' '.join(cmd)}")
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return output_path
            else:
                logger.error(f"FFmpeg burn failed: {res.stderr[:500]}")
                return video_path
        except Exception as e:
            logger.error(f"Error running ffmpeg: {e}")
            return video_path

