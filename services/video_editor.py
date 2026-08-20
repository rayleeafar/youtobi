import os
import re
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("youtobi.video_editor")

class VideoEditor:
    @staticmethod
    def escape_drawtext(text: str) -> str:
        """Escapes special characters for FFmpeg drawtext filter."""
        if not text:
            return ""
        # Escape backslash, single quote, colon, percent, and brackets
        t = text.replace("\\", "\\\\")
        t = t.replace("'", "\\\x27")
        t = t.replace(":", "\\:")
        t = t.replace("%", "\\%")
        return t

    @classmethod
    def build_filter_chain(
        cls,
        flip_horizontal: bool = False,
        border_ratio: float = 0.0,
        watermark_text: str = "",
        watermark_opacity: float = 0.012,
        srt_path: Optional[Path] = None
    ) -> str:
        """
        Builds a combined FFmpeg video filter (-vf) string for:
        1. Horizontal image flipping (hflip)
        2. Configurable black border scaling & padding (scale + pad)
        3. Subtitle burn-in (subtitles)
        4. Invisible / Extreme-contrast watermark (drawtext)
        """
        filters: List[str] = []

        # 1. Image Mirroring / Horizontal Flip
        if flip_horizontal:
            filters.append("hflip")

        # 2. Configurable Black Borders / Margin Padding
        if border_ratio and border_ratio > 0.001:
            ratio = min(max(border_ratio, 0.01), 0.25)
            scale_factor = round(1.0 - 2.0 * ratio, 4)
            # Scale video down and pad back to canvas with black background
            filters.append(
                f"scale=w=trunc(iw*{scale_factor}/2)*2:h=trunc(ih*{scale_factor}/2)*2,"
                f"pad=w=trunc(iw/{scale_factor}/2)*2:h=trunc(ih/{scale_factor}/2)*2:"
                f"x=(ow-iw)/2:y=(oh-ih)/2:color=black"
            )

        # 3. Subtitle Burn-In
        if srt_path and Path(srt_path).exists():
            srt_escaped = str(Path(srt_path).resolve()).replace("\\", "/").replace(":", "\\:")
            filters.append(
                f"subtitles='{srt_escaped}':"
                f"force_style='FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1'"
            )

        # 4. Invisible / Extreme-Contrast Steganographic Watermark
        if watermark_text and watermark_text.strip():
            escaped_text = cls.escape_drawtext(watermark_text.strip())
            opacity = min(max(watermark_opacity, 0.001), 0.5)
            filters.append(
                f"drawtext=text='{escaped_text}':"
                f"fontcolor=white@{opacity}:"
                f"fontsize=h/22:"
                f"x=(w-tw)/2:y=h*0.82:"
                f"shadowcolor=black@{opacity}:shadowx=1:shadowy=1"
            )

        return ",".join(filters)

    def process_video(
        self,
        video_path: Path,
        output_path: Path,
        flip_horizontal: bool = False,
        border_ratio: float = 0.0,
        watermark_text: str = "",
        watermark_opacity: float = 0.012,
        srt_path: Optional[Path] = None,
        preset: str = "fast",
        progress_callback = None
    ) -> Path:
        """
        Applies secondary video transformations and subtitle burn-in in a single FFmpeg pass.
        Returns output_path on success, or original video_path if no transformations are needed / failed.
        """
        video_path = Path(video_path)
        output_path = Path(output_path)

        filter_str = self.build_filter_chain(
            flip_horizontal=flip_horizontal,
            border_ratio=border_ratio,
            watermark_text=watermark_text,
            watermark_opacity=watermark_opacity,
            srt_path=srt_path
        )

        if not filter_str:
            logger.info("No video filters requested. Skipping video re-encoding.")
            return video_path

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", filter_str,
            "-c:v", "libx264",
            "-preset", preset,
            "-c:a", "aac",
            str(output_path)
        ]

        logger.info(f"Running VideoEditor FFmpeg command: {" ".join(cmd)}")
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                logger.info(f"Successfully processed secondary video: {output_path}")
                return output_path
            else:
                logger.error(f"VideoEditor FFmpeg failed (code {res.returncode}): {res.stderr[:500]}")
                return video_path
        except Exception as e:
            logger.error(f"Error running VideoEditor FFmpeg: {e}")
            return video_path
