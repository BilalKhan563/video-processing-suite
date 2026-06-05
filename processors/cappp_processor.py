import os
import shutil
import subprocess
import tempfile
import uuid
import requests
import pysubs2
import whisper
import json
import traceback
import time
import threading
from typing import Tuple
import cloudinary
import cloudinary.uploader

# Configuration
CLOUDINARY_CONFIG = {
    "cloud_name": os.environ.get("CLOUDINARY_CLOUD_NAME"),
    "api_key": os.environ.get("CLOUDINARY_API_KEY"),
    "api_secret": os.environ.get("CLOUDINARY_API_SECRET"),
    "secure": True
}
cloudinary.config(**CLOUDINARY_CONFIG)

TMP_ROOT = "/tmp/video_merge_cappp"
os.makedirs(TMP_ROOT, exist_ok=True)

FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

# Global Whisper Model variable with thread-safe loading
_whisper_model = None
_model_lock = threading.Lock()


def get_whisper_model():
    global _whisper_model
    with _model_lock:
        if _whisper_model is None:
            print("🚀 Loading Whisper Model (Tiny) for CAPPP...")
            # Use tiny model - MUCH faster on CPU (only 39MB vs 139MB for base)
            _whisper_model = whisper.load_model(
                "tiny",
                device="cpu",
                download_root="/tmp/whisper_models"
            )
            print("✅ Whisper Model loaded successfully")
    return _whisper_model


# --------------------------- Helper Functions ---------------------------

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
    try:
        dim = result.stdout.strip().split(',')
        return (int(dim[0]), int(dim[1])) if len(dim) == 2 else (1080, 1920)
    except:
        return (1080, 1920)


def burn_exact_styled_captions(video_path: str, subs: pysubs2.SSAFile, out_path: str):
    sub_path = os.path.join(os.path.dirname(video_path), f"temp_{uuid.uuid4().hex}.ass")

    # Use a font that's guaranteed to exist on Railway/Linux
    style = pysubs2.SSAStyle(
        fontname="DejaVu Sans",  # Standard Linux font
        fontsize=18,
        bold=True,
        primarycolor=pysubs2.Color(255, 255, 255),
        outlinecolor=pysubs2.Color(0, 0, 0),
        borderstyle=1,
        outline=1.5,
        shadow=0,
        alignment=5,  # Center-Center
        marginv=0
    )
    subs.styles["Default"] = style

    for event in subs.events:
        event.text = event.text.upper()

    subs.save(sub_path)

    # Railway is Linux, so we use standard paths
    escaped_path = os.path.abspath(sub_path)
    filter_str = f"subtitles='{escaped_path}'"

    print(f"   📝 Applying ASS subtitles from: {sub_path}")

    cmd = [
        FFMPEG_BIN, "-y", "-i", video_path,
        "-vf", filter_str,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
        "-c:a", "copy", out_path
    ]
    run_cmd(cmd)

    # Clean up subtitle file
    try:
        os.remove(sub_path)
    except:
        pass


# --------------------------- Main Logic ---------------------------

def run_cappp_logic(payload: dict):
    """The entry point for app.py - Integrated with Metadata Passthrough"""
    print("=" * 50)
    print("🚀 Starting CAPP processing...")
    print(f"📦 Payload keys: {list(payload.keys())}")

    job_id = payload.get("job_id", str(uuid.uuid4()))
    tmp_dir = tempfile.mkdtemp(dir=TMP_ROOT)
    callback_url = payload.get("callback_url")

    # EXTRACT METADATA (Optional fields default to empty strings)
    script_hook = payload.get("script_hook", "")
    script_captions = payload.get("script_captions", "")
    thumbnail_url = payload.get("thumbnail_url", "")
    youtube_title = payload.get("youtube_title", "")

    print(f"🎯 Job ID: {job_id}")
    print(f"📞 Callback URL: {callback_url}")
    print(f"📁 Temp directory: {tmp_dir}")

    try:
        # 1. Validate and extract video URLs
        v1_url = str(payload.get("video1_url", ""))
        v2_url = str(payload.get("video2_url", ""))

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

        # 3. Load Whisper and Transcribe
        model = get_whisper_model()

        def generate_subs(video, video_name):
            print(f"   Transcribing {video_name}...")
            start_time = time.time()
            try:
                result = model.transcribe(video, word_timestamps=True, language="en")
                elapsed = time.time() - start_time
                print(f"   ⏱️ Transcription took {elapsed:.1f} seconds")

                subs = pysubs2.SSAFile()
                words_acc = []

                for segment in result["segments"]:
                    for word in segment["words"]:
                        words_acc.append(word)
                        # Your custom logic: 2 words or end of sentence
                        if len(words_acc) >= 2 or any(word['word'].strip().endswith(p) for p in ['.', '!', '?']):
                            text = " ".join([w['word'].strip() for w in words_acc])
                            start, end = int(words_acc[0]['start'] * 1000), int(words_acc[-1]['end'] * 1000)
                            if end - start < 500:
                                end = start + 500
                            subs.events.append(pysubs2.SSAEvent(start=start, end=end, text=text))
                            words_acc = []
                return subs
            except Exception as e:
                print(f"   ❌ Transcription failed for {video_name}: {str(e)}")
                raise

        subs1 = generate_subs(v1_path, "Video 1")
        subs2 = generate_subs(v2_path, "Video 2")

        # 4. Concatenate Videos
        concat_path = os.path.join(tmp_dir, "concat.mp4")
        w, h = get_video_dimensions(v1_path)
        filter_complex = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[v0];[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[v1];[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[outv][outa]"

        run_cmd([FFMPEG_BIN, "-y", "-i", v1_path, "-i", v2_path, "-filter_complex", filter_complex, "-map", "[outv]",
                 "-map", "[outa]", concat_path])

        # 5. Offset and Merge subtitles
        v1_dur = float(run_cmd([FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of",
                                "default=noprint_wrappers=1:nokey=1", v1_path]).strip())
        for e in subs2.events:
            e.start += int(v1_dur * 1000)
            e.end += int(v1_dur * 1000)

        merged_subs = pysubs2.SSAFile()
        merged_subs.events = subs1.events + subs2.events

        # 6. Burn & Upload
        final_video = os.path.join(tmp_dir, f"final_{job_id}.mp4")
        burn_exact_styled_captions(concat_path, merged_subs, final_video)

        res = cloudinary.uploader.upload(final_video, resource_type="video", folder="cappp_videos")
        final_url = res.get("secure_url")

        # 7. Success Response with metadata echoed back
        success_response = {
            "status": "success",
            "url": final_url,
            "job_id": job_id,
            "script_hook": script_hook,
            "script_captions": script_captions,
            "thumbnail_url": thumbnail_url,
            "youtube_title": youtube_title,
            "video1_duration": v1_dur,
            "total_segments": len(merged_subs.events),
            "style": "social_media_uppercase",
            "timestamp": time.time()
        }

        if callback_url:
            requests.post(callback_url, json=success_response, timeout=30)

        print(f"✅ CAPP processing completed successfully for job {job_id}")
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