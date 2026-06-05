"""
Dynamic/BICEP caption style (from cap_dynamic.py)
- Word-by-word timing
- Color effects based on word meaning
- Pop/zoom animations
- Syllable-aware timing
"""
import re
import pysubs2
from typing import Tuple, List
from .base_style import BaseCaptionStyle


class DynamicCaptionStyle(BaseCaptionStyle):
    """Dynamic style with word-by-word effects and color coding"""

    # Color codes (ASS: &HBBGGRR&)
    COLORS = {
        'success': "&H00FF00&",  # Green - money, profit, sold
        'warning': "&H0000FF&",  # Red - urgent, danger
        'luxury': "&H00D7FF&",  # Gold - luxury, premium
        'action': "&HFFFF00&",  # Cyan - action verbs
        'data': "&HFFCC00&",  # Light blue - numbers, facts
        'default': "&H00FFFF&"  # Cyan default
    }

    # Effect animations
    EFFECTS = {
        'pop': "\\fscx220\\fscy220\\t(0,200,\\fscx120\\fscy120)",
        'shake': "\\fscx160\\fscy160\\t(0,50,\\frz5)\\t(50,100,\\frz-5)\\t(100,150,\\frz0)",
        'grow': "\\fscx200\\fscy200\\t(0,250,\\fscx115\\fscy115)",
        'tilt': "\\frz-8\\fscx130\\fscy130\\t(0,150,\\frz0)",
        'highlight': "\\fscx140\\fscy140\\b1",
        'none': ""
    }

    def __init__(self):
        super().__init__()
        self.name = "dynamic"
        self.font_name = "Montserrat ExtraBold"
        self.font_size = 120
        self.alignment = 2  # Bottom-center for video 1
        self.outline = 4.0
        self.primary_color = pysubs2.Color(255, 255, 0)  # Yellow when spoken
        self.secondary_color = pysubs2.Color(255, 255, 255)  # White initial
        self.back_color = pysubs2.Color(0, 0, 0, 180)
        self.margin_l = 250
        self.margin_r = 250
        self.margin_v = 100

    def get_word_effect(self, word: str) -> Tuple[str, str]:
        """
        Determine color and effect for a word based on its meaning

        Returns:
            Tuple of (color_code, effect_string)
        """
        w = word.lower().strip(".,!?;:\"")

        # 1. SUCCESS, MONEY & CLOSING (Green + Massive Pop)
        success_words = {
            "sold", "profit", "equity", "wealth", "deal", "closed", "cash", "million",
            "win", "huge", "investment", "roi", "income", "buyer", "seller", "contract",
            "escrow", "appraisal", "closing", "mortgage", "financing", "capital",
            "off-market", "portfolio", "assets", "wealthy", "rich", "save", "money",
            "check", "bank", "deposit", "funding", "commission", "revenue"
        }
        if w in success_words:
            return self.COLORS['success'], self.EFFECTS['pop']

        # 2. URGENCY, WARNING & SCARCITY (Red + Shake)
        warning_words = {
            "listed", "drop", "warning", "stop", "alert", "urgent", "danger", "now",
            "limited", "hurry", "fast", "mistake", "never", "avoid", "risk", "deadline",
            "last", "chance", "expired", "don't", "wait", "scary", "broke", "lost",
            "fail", "caution", "hidden", "secret"
        }
        if w in warning_words:
            return self.COLORS['warning'], self.EFFECTS['shake']

        # 3. LUXURY & INTERIORS (Gold + Elegant Grow)
        luxury_words = {
            "luxury", "tips", "dream", "stunning", "mansion", "exclusive", "view",
            "penthouse", "modern", "renovated", "kitchen", "bathroom", "pool",
            "backyard", "location", "realtor", "broker", "gorgeous", "beautiful",
            "custom", "granite", "marble", "spa", "deck", "estate", "design",
            "lifestyle", "elite", "prime", "classic", "updated", "master", "suite",
            "amenities"
        }
        if w in luxury_words:
            return self.COLORS['luxury'], self.EFFECTS['grow']

        # 4. PROPERTY & STRUCTURE (Cyan + Punchy Tilt)
        action_words = {
            "build", "strategy", "grow", "buy", "sell", "construction", "material",
            "move", "find", "search", "negotiate", "leads", "marketing", "rent",
            "lease", "flip", "renovate", "upgrade", "house", "home", "property",
            "land", "unit", "keys", "door", "step", "start", "condo", "townhouse"
        }
        if w in action_words:
            return self.COLORS['action'], self.EFFECTS['tilt']

        # 5. DATA & NUMBERS (Light Blue + Highlight)
        data_words = {
            "market", "data", "stats", "percent", "rate", "interest", "numbers",
            "tax", "facts", "proven", "results", "guaranteed", "trust", "expert",
            "local", "history", "years", "value", "price", "cost", "fee", "points",
            "math", "analysis", "inventory", "comps"
        }
        if w in data_words:
            return self.COLORS['data'], self.EFFECTS['highlight']

        # Default - active color, no effect
        return self.COLORS['default'], self.EFFECTS['none']

    def count_syllables(self, word: str) -> int:
        """Count syllables in a word for timing"""
        word = word.lower().strip(".,!?;:\"")
        if len(word) <= 3:
            return 1

        count = len(re.findall(r'[aeiouy]+', word))
        if word.endswith('e'):
            count -= 1

        return max(1, count)

    def style_subtitle(self, text: str, duration_ms: int) -> str:
        """
        Apply dynamic word-by-word styling

        Each word gets:
        - Color based on meaning
        - Animation effect
        - Syllable-weighted duration (karaoke timing)
        """
        if not text:
            return ""

        # Clean text
        text = self._clean_text(text)

        # Split into words
        words = text.split()
        if not words:
            return text

        # Calculate syllable counts
        word_syllables = [self.count_syllables(w) for w in words]
        total_syllables = sum(word_syllables) if sum(word_syllables) > 0 else len(words)

        # Total duration in centiseconds (100ths of a second)
        total_cs = duration_ms // 10

        styled_chunks = []

        for i, word in enumerate(words):
            # Clean word for lookup
            clean_word = re.sub(r"[^\w]", "", word).lower()
            color, effect = self.get_word_effect(clean_word)

            # Syllable-weighted duration
            syl_count = word_syllables[i]
            word_weight = syl_count / total_syllables
            word_duration_cs = max(1, int(total_cs * word_weight))

            # Apply styling
            if color != self.COLORS['default']:
                # Effect word - has color and animation
                styled_word = f"{{\\1c{color}{effect}}}{word.upper()}{{\\r}}"
            else:
                # Normal word - just karaoke timing
                styled_word = f"{{\\k{word_duration_cs}}}{word}{{\\r}}"

            styled_chunks.append(styled_word)

        # Join with spaces
        result = " ".join(styled_chunks)

        return result

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text for styling"""
        # Remove existing ASS tags
        text = re.sub(r"\{[^}]*\}", "", text)

        # Remove BOM
        text = text.replace('\ufeff', '')

        # Normalize apostrophes
        text = text.replace("\u2018", "'").replace("\u2019", "'").replace("`", "'")

        # Remove double commas
        text = text.replace(",,", "")

        # Normalize newlines to spaces
        text = text.replace("\\n", " ").replace("\\N", " ").replace("\n", " ").replace("\r", " ")

        # Remove non-breaking spaces
        text = text.replace("\xa0", " ")

        # Fix contractions (don't, won't, etc.)
        text = re.sub(r"(\w+)\s+'\s+(\w+)", r"\1'\2", text)
        text = re.sub(r"(\w+)\s+n't", r"\1n't", text, flags=re.IGNORECASE)

        # Fix punctuation spacing
        text = re.sub(r"(^|\s),+([A-Za-z])", r"\1\2", text)
        text = re.sub(r'\.\s*,+', ".", text)

        # Normalize whitespace
        text = ' '.join(text.split())

        return text.strip()


# Video 2 style (different position)
class DynamicCaptionStyleVideo2(DynamicCaptionStyle):
    """Dynamic style for video 2 - centered, slightly smaller"""

    def __init__(self):
        super().__init__()
        self.name = "dynamic_v2"
        self.font_size = 85
        self.alignment = 5  # Center-center
        self.margin_v = 150


def burn_dynamic_captions(video_path: str, subs: pysubs2.SSAFile, out_path: str,
                          style_type: str = "v1"):
    """
    Burn dynamic captions using ASS file with advanced styling

    Args:
        video_path: Input video path
        subs: Subtitle events
        out_path: Output video path
        style_type: "v1" for larger bottom-center, "v2" for centered
    """
    import subprocess
    import time
    import uuid

    # Choose style
    if style_type == "v1":
        style = DynamicCaptionStyle()
    else:
        style = DynamicCaptionStyleVideo2()

    # Apply style name to events
    for event in subs.events:
        event.style = style.name

    # Create and register style
    subs.styles[style.name] = style.create_style()
    subs.info["PlayResX"], subs.info["PlayResY"] = 1080, 1920

    # Save ASS file
    ass_path = f"/tmp/sub_{uuid.uuid4().hex}.ass"
    subs.save(ass_path)

    # Escape for FFmpeg
    clean_ass = ass_path.replace("\\", "/").replace(":", "\\:")

    # Get video duration
    cmd_duration = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'csv=p=0', video_path]
    result = subprocess.run(cmd_duration, capture_output=True, text=True)
    video_dur_s = float(result.stdout.strip())

    # Check if video needs extension
    last_sub_end_s = max(e.end for e in subs.events) / 1000.0
    extra_s = max(0.0, last_sub_end_s - video_dur_s)

    source_path = video_path
    padded_path = None

    if extra_s > 0.05:
        print(f"Extending video by {extra_s:.2f}s to cover subtitles")
        padded_path = video_path.replace(".mp4", "_padded.mp4")

        pad_cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f"tpad=stop_mode=clone:stop_duration={extra_s:.3f}",
            '-af', f"apad=pad_dur={extra_s:.3f}",
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18',
            '-c:a', 'aac', padded_path
        ]
        subprocess.run(pad_cmd, check=True, capture_output=True)
        source_path = padded_path

    # Burn captions
    margin_settings = style.get_margin_settings()

    cmd = [
        'ffmpeg', '-y', '-i', source_path,
        '-vf', f"subtitles='{clean_ass}':force_style='MarginL={margin_settings['margin_l']},"
               f"MarginR={margin_settings['margin_r']},WrapStyle=2'",
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18',
        '-c:a', 'copy', out_path
    ]

    subprocess.run(cmd, check=True, capture_output=True)

    # Cleanup
    if os.path.exists(ass_path):
        os.remove(ass_path)
    if padded_path and os.path.exists(padded_path):
        os.remove(padded_path)


# Utility function for word effects (exported for use elsewhere)
def apply_bicep_style_to_text(text: str, total_duration_ms: int) -> str:
    """
    Apply BICEP-style word effects to text

    This is the main function used by cap_dynamic.py
    """
    style = DynamicCaptionStyle()
    return style.style_subtitle(text, total_duration_ms)