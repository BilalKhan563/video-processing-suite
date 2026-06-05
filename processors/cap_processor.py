import os
import shutil
import subprocess
import tempfile
import time
import uuid
import requests
import pysubs2
import whisper
import json
import traceback
import threading
from typing import Tuple
import cloudinary
import cloudinary.uploader

# Configuration (Railway will inject these from Environment Variables)
CLOUDINARY_CONFIG = {
    "cloud_name": os.environ.get("CLOUDINARY_CLOUD_NAME"),
    "api_key": os.environ.get("CLOUDINARY_API_KEY"),
    "api_secret": os.environ.get("CLOUDINARY_API_SECRET"),
    "secure": True
}
cloudinary.config(**CLOUDINARY_CONFIG)

# Use /tmp for Railway (standard Linux temp directory)
TMP_ROOT = "/tmp/video_merge"
os.makedirs(TMP_ROOT, exist_ok=True)

# Railway uses Linux, so we default to 'ffmpeg'
FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

# Global Whisper Model variable with thread-safe loading
_whisper_model = None
_model_lock = threading.Lock()


def get_whisper_model():
    global _whisper_model
    with _model_lock:
        if _whisper_model is None:
            print("🚀 Loading Whisper Model (Tiny)...")
            # Use tiny model for better performance on Railway CPU
            # Tiny: 39MB, 4x faster than base, sufficient quality for captions
            _whisper_model = whisper.load_model(
                "tiny",
                device="cpu",
                download_root="/tmp/whisper_models"
            )
            print("✅ Whisper Model loaded successfully")
    return _whisper_model


# --------------------------- Logic Functions ---------------------------

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ FFmpeg Error: {e.stderr}")
        raise Exception(f"FFmpeg failed: {e.stderr}")


def get_video_dimensions(video_path: str) -> Tuple[int, int]:
    cmd = [FFPROBE_BIN, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of',
           'csv=p=0', video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    dim = result.stdout.strip().split(',')
    return (int(dim[0]), int(dim[1])) if len(dim) == 2 else (1080, 1920)


def escape_ffmpeg_text(text: str) -> str:
    """
    Properly escape text for FFmpeg's drawtext filter while preserving apostrophes
    """
    # Remove BOM and other invisible characters
    text = text.replace('\ufeff', '')

    # Keep apostrophes - they're safe in drawtext
    # Escape special FFmpeg characters: colon, comma, backslash, single quote in content
    text = text.replace('\\', '\\\\')  # Backslash first
    text = text.replace(':', '\\:')  # Colon
    text = text.replace(',', '\\,')  # Comma
    # NOTE: Apostrophes are NOT escaped - they're fine in drawtext filter

    return text


def wrap_text(text: str, max_chars_per_line: int = 30) -> str:
    """
    Wrap text to multiple lines if it exceeds max_chars_per_line
    This prevents horizontal overflow while keeping text readable
    """
    words = text.split()
    if not words:
        return text

    lines = []
    current_line = []
    current_length = 0

    for word in words:
        word_length = len(word)
        # Account for spaces between words
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


def burn_exact_styled_captions(video_path: str, subs: pysubs2.SSAFile, out_path: str):
    """
    Burn captions with proper edge margins and apostrophe handling
    """
    width, height = get_video_dimensions(video_path)
    y_pos = int(height * 0.55)
    fixed_f_size = int(width * 0.055)

    # Font path - Linux doesn't have Windows fonts
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not os.path.exists(font_path):
        font_path = "DejaVuSans-Bold"
        print(f"⚠️ Using fallback font: {font_path}")

    padding = int(fixed_f_size * 0.4)

    # Edge margins: 10% of width on each side prevents text from reaching edges
    left_margin = int(width * 0.10)
    right_margin = int(width * 0.10)
    usable_width = width - left_margin - right_margin

    print(f"   📐 Video dimensions: {width}x{height}")
    print(f"   📐 Font size: {fixed_f_size}, Y position: {y_pos}")
    print(f"   📐 Left margin: {left_margin}, Right margin: {right_margin}, Usable width: {usable_width}")

    filter_chains = []

    for idx, event in enumerate(subs.events):
        # Escape text properly while KEEPING apostrophes
        clean_text = escape_ffmpeg_text(event.text)

        # Wrap text if too long (estimate: ~3-4 chars per pixel at this font size)
        max_chars = max(20, usable_width // (fixed_f_size * 0.5))
        wrapped_text = wrap_text(clean_text, int(max_chars))

        start = event.start / 1000.0
        end = event.end / 1000.0

        # Position text in the center with left/right margins
        # Using (w-text_w)/2 centers it, but limit it to respect margins
        drawtext = (
            f"drawtext=fontfile='{font_path}'"
            f":text='{wrapped_text}'"
            f":fontcolor=white:fontsize={fixed_f_size}"
            f":x=max({left_margin}\\,min(w-text_w-{right_margin}\\,(w-text_w)/2)):y={y_pos}-(th/2)"
            f":box=1:boxcolor=black@0.80:boxborderw={padding}"
            f":enable='between(t\\,{start}\\,{end})'"
        )
        filter_chains.append(drawtext)

        if idx < 3:  # Log first 3 for debugging
            print(f"   📝 Caption {idx + 1}: '{event.text}' → '{wrapped_text}' ({start:.2f}s - {end:.2f}s)")

    full_filter = ",".join(filter_chains)
    print(f"   🎬 Applying caption filter with {len(filter_chains)} segments")

    cmd = [
        FFMPEG_BIN, "-y", "-i", video_path,
        "-vf", full_filter,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "copy", out_path
    ]
    run_cmd(cmd)


def run_cap_logic(payload: dict):
    """This function processes the video and echoes back metadata for tracking."""
    print("=" * 50)
    print("🚀 Starting CAP processing...")
    print(f"📦 Payload keys: {list(payload.keys())}")

    job_id = payload.get("job_id", str(uuid.uuid4()))
    tmp_dir = tempfile.mkdtemp(dir=TMP_ROOT)
    callback_url = payload.get("callback_url")

    # EXTRACT METADATA: Hook and Captions are distinct
    script_hook = payload.get("script_hook", "")
    script_captions = payload.get("script_captions", "")
    thumbnail_url = payload.get("thumbnail_url", "")
    youtube_title = payload.get("youtube_title", "")

    print(f"🎯 Job ID: {job_id}")
    print(f"📁 Temp directory: {tmp_dir}")

    try:
        # 1. Validate and extract video URLs
        v1_url = payload.get("video1_url")
        v2_url = payload.get("video2_url")

        if not v1_url or not v2_url:
            error_msg = f"Missing video URLs. video1_url: {v1_url}, video2_url: {v2_url}"
            print(f"❌ {error_msg}")

            if callback_url:
                requests.post(callback_url, json={
                    "status": "error",
                    "message": error_msg,
                    "job_id": job_id,
                    "script_hook": script_hook,
                    "youtube_title": youtube_title,
                    "timestamp": time.time()
                }, timeout=10)
            raise ValueError(error_msg)

        # 2. Download Files
        v1_path = os.path.join(tmp_dir, "v1.mp4")
        v2_path = os.path.join(tmp_dir, "v2.mp4")

        for url, path in [(v1_url, v1_path), (v2_url, v2_path)]:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            with open(path, 'wb') as f:
                f.write(response.content)

        # 3. Transcribe
        model = get_whisper_model()
        res1 = model.transcribe(v1_path, language="en")
        res2 = model.transcribe(v2_path, language="en")

        subs1 = pysubs2.SSAFile()
        for s in res1['segments']:
            subs1.events.append(
                pysubs2.SSAEvent(start=int(s['start'] * 1000), end=int(s['end'] * 1000), text=s['text']))

        subs2 = pysubs2.SSAFile()
        for s in res2['segments']:
            subs2.events.append(
                pysubs2.SSAEvent(start=int(s['start'] * 1000), end=int(s['end'] * 1000), text=s['text']))

        # 4. Concatenate
        concat_path = os.path.join(tmp_dir, "concat.mp4")
        w, h = get_video_dimensions(v1_path)
        filter_complex = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[v0];[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[v1];[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[outv][outa]"

        run_cmd([FFMPEG_BIN, "-y", "-i", v1_path, "-i", v2_path, "-filter_complex", filter_complex, "-map", "[outv]",
                 "-map", "[outa]", concat_path])

        v1_dur = float(run_cmd([FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of",
                                "default=noprint_wrappers=1:nokey=1", v1_path]))
        for e in subs2.events:
            e.start += int(v1_dur * 1000)
            e.end += int(v1_dur * 1000)

        merged_subs = pysubs2.SSAFile()
        merged_subs.events = subs1.events + subs2.events

        # 5. Burn captions & Upload
        final_video = os.path.join(tmp_dir, "final.mp4")
        burn_exact_styled_captions(concat_path, merged_subs, final_video)

        res = cloudinary.uploader.upload(final_video, resource_type="video", folder="cap_videos")
        final_url = res.get("secure_url")

        # 6. Webhook Response (Success)
        v2_dur = float(run_cmd([FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of",
                                "default=noprint_wrappers=1:nokey=1", v2_path]))

        success_response = {
            "status": "success",
            "url": final_url,
            "job_id": job_id,
            "script_hook": script_hook,
            "script_captions": script_captions,
            "thumbnail_url": thumbnail_url,
            "youtube_title": youtube_title,
            "video1_duration": v1_dur,
            "video2_duration": v2_dur,
            "timestamp": time.time()
        }

        if callback_url:
            requests.post(callback_url, json=success_response, timeout=30)

        return success_response

    except Exception as e:
        if callback_url:
            requests.post(callback_url, json={
                "status": "error",
                "message": str(e),
                "job_id": job_id,
                "script_hook": script_hook,
                "youtube_title": youtube_title,
                "timestamp": time.time()
            }, timeout=10)
        raise

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)