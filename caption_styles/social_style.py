"""
Social media caption style (from cap_b&w.py)
- Uppercase text for impact
- ASS subtitle format for better styling
- Bold, attention-grabbing
"""
import os
import uuid
import pysubs2
from .base_style import BaseCaptionStyle


class SocialCaptionStyle(BaseCaptionStyle):
    """Social media style - uppercase, bold, center-aligned"""

    def __init__(self):
        super().__init__()
        self.name = "social"
        self.font_name = "DejaVu Sans"
        self.font_size = 85
        self.alignment = 5  # Center-center
        self.outline = 3.0
        self.primary_color = pysubs2.Color(255, 255, 255)
        self.back_color = pysubs2.Color(0, 0, 0, 180)
        self.margin_l = 150
        self.margin_r = 150
        self.margin_v = 200

    def style_subtitle(self, text: str, duration_ms: int) -> str:
        """Apply social media styling - UPPERCASE + bold"""
        # Clean existing tags
        import re
        text = re.sub(r"\{[^}]*\}", "", text)

        # Convert to uppercase
        text = text.upper()

        # Add basic styling
        text = f"{{\\b1}}{text}{{\\b0}}"

        return text


def burn_social_captions(video_path: str, subs: pysubs2.SSAFile, out_path: str):
    """
    Burn captions using ASS subtitle file with social media styling
    """
    # Create style
    style = pysubs2.SSAStyle(
        fontname="DejaVu Sans",
        fontsize=85,
        bold=True,
        primarycolor=pysubs2.Color(255, 255, 255),
        outlinecolor=pysubs2.Color(0, 0, 0),
        borderstyle=1,
        outline=2.5,
        shadow=0,
        alignment=5,  # Center-center
        marginv=200,
        marginl=150,
        marginr=150
    )

    # Apply style to all events
    subs.styles["Default"] = style

    # Convert text to uppercase
    for event in subs.events:
        import re
        clean_text = re.sub(r"\{[^}]*\}", "", event.text)
        event.text = clean_text.upper()

    # Save ASS file
    ass_path = os.path.join("/tmp", f"sub_{uuid.uuid4().hex}.ass")
    subs.save(ass_path)

    # Burn using FFmpeg
    escaped_path = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")

    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vf', f"subtitles='{escaped_path}'",
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '24',
        '-c:a', 'copy', out_path
    ]

    import subprocess
    subprocess.run(cmd, check=True, capture_output=True)

    # Cleanup
    if os.path.exists(ass_path):
        os.remove(ass_path)