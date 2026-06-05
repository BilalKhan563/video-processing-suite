"""
Basic caption style (from cap_w.py)
- Clean, readable captions
- Center-bottom position
- Black background box
- Proper text wrapping and escaping
"""
import os
import subprocess
import uuid
import pysubs2
from typing import Tuple
from .base_style import BaseCaptionStyle


class BasicCaptionStyle(BaseCaptionStyle):
    """Basic styled captions with box background"""

    def __init__(self):
        super().__init__()
        self.name = "basic"
        self.font_name = "DejaVu Sans"
        self.font_size = 85
        self.alignment = 5  # Center-center
        self.outline = 4.0
        self.primary_color = pysubs2.Color(255, 255, 255)
        self.back_color = pysubs2.Color(0, 0, 0, 200)
        self.margin_l = 250
        self.margin_r = 250
        self.margin_v = 150

    def style_subtitle(self, text: str, duration_ms: int) -> str:
        """Basic styling - no effects, just clean text"""
        # Clean and prepare text
        text = self._clean_text(text)

        # Wrap text if too long
        max_chars = 35
        if len(text) > max_chars:
            text = self._wrap_text(text, max_chars)

        return text

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        # Remove existing ASS tags
        import re
        text = re.sub(r"\{[^}]*\}", "", text)

        # Remove BOM and special characters
        text = text.replace('\ufeff', '')

        # Normalize apostrophes
        text = text.replace("\u2018", "'").replace("\u2019", "'").replace("`", "'")

        # Remove double commas
        text = text.replace(",,", "")

        # Normalize whitespace
        text = ' '.join(text.split())

        return text.strip()

    def _wrap_text(self, text: str, max_chars: int) -> str:
        """Wrap text to multiple lines"""
        words = text.split()
        if not words:
            return text

        lines = []
        current_line = []
        current_length = 0

        for word in words:
            word_length = len(word)
            potential_length = current_length + word_length + (1 if current_line else 0)

            if potential_length <= max_chars:
                current_line.append(word)
                current_length = potential_length
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_length = word_length

        if current_line:
            lines.append(' '.join(current_line))

        return '\\N'.join(lines)

    def get_margin_settings(self) -> dict:
        """Get margin settings for this style"""
        return {
            "margin_l": 250,
            "margin_r": 250,
            "margin_v": 150
        }


def escape_ffmpeg_text(text: str) -> str:
    """Escape text for FFmpeg drawtext filter"""
    text = text.replace('\\', '\\\\')
    text = text.replace(':', '\\:')
    text = text.replace(',', '\\,')
    text = text.replace("'", "\\'")
    text = text.replace('"', '\\"')
    return text


def wrap_text(text: str, max_chars_per_line: int = 30) -> str:
    """Wrap text to multiple lines"""
    words = text.split()
    if not words:
        return text

    lines = []
    current_line = []
    current_length = 0

    for word in words:
        word_length = len(word)
        potential_length = current_length + word_length + (1 if current_line else 0)

        if potential_length <= max_chars_per_line:
            current_line.append(word)
            current_length = potential_length
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
            current_length = word_length

    if current_line:
        lines.append(' '.join(current_line))

    return '\\n'.join(lines)


def get_video_dimensions(video_path: str) -> Tuple[int, int]:
    """Get video dimensions using ffprobe"""
    import subprocess
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
           '-show_entries', 'stream=width,height', '-of', 'csv=p=0', video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    dim = result.stdout.strip().split(',')
    return (int(dim[0]), int(dim[1])) if len(dim) == 2 else (1080, 1920)


def burn_basic_captions(video_path: str, subs: pysubs2.SSAFile, out_path: str):
    """
    Burn captions using FFmpeg drawtext filter (no ASS file)
    """
    width, height = get_video_dimensions(video_path)
    y_pos = int(height * 0.55)
    font_size = int(width * 0.055)

    # Font path for Linux
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not os.path.exists(font_path):
        font_path = "DejaVuSans-Bold"

    padding = int(font_size * 0.4)
    left_margin = int(width * 0.10)
    right_margin = int(width * 0.10)

    filter_chains = []

    for event in subs.events:
        clean_text = escape_ffmpeg_text(event.text)
        wrapped_text = wrap_text(clean_text, 30)
        start = event.start / 1000.0
        end = event.end / 1000.0

        drawtext = (
            f"drawtext=fontfile='{font_path}'"
            f":text='{wrapped_text}'"
            f":fontcolor=white:fontsize={font_size}"
            f":x=max({left_margin}\\,min(w-text_w-{right_margin}\\,(w-text_w)/2))"
            f":y={y_pos}-(th/2)"
            f":box=1:boxcolor=black@0.80:boxborderw={padding}"
            f":enable='between(t\\,{start}\\,{end})'"
        )
        filter_chains.append(drawtext)

    full_filter = ",".join(filter_chains)

    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vf', full_filter,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
        '-c:a', 'copy', out_path
    ]

    subprocess.run(cmd, check=True, capture_output=True)