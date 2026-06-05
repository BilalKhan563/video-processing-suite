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
import threading
import re
from typing import Tuple, Dict, Any, Optional
from pathlib import Path
import cloudinary
import cloudinary.uploader
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Request
import logging

# =========================
# Logging Configuration
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================= 1. ENV LOADING =================
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    os.environ[parts[0]] = parts[1]

# ================= 2. CONFIGURATION =================
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)

app = FastAPI(title="Railway Video Processing Suite")

TMP_ROOT = os.path.join(tempfile.gettempdir(), "video_merge")
os.makedirs(TMP_ROOT, exist_ok=True)

FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

MIN_MS_PER_WORD = 350   # Minimum ms each word needs to be visible
CHAR_LIMIT = 18         # Max visual chars per caption line (safe for fontsize 85 bold + 250px margins)


# ================= 4. SURGICAL WORD EFFECTS =================

def get_word_effect(word: str) -> Tuple[str, str]:
    w = word.lower().strip(".,!?;:\"")

    # 1. SUCCESS, MONEY & CLOSING (Vibrant Green + Massive Pop)
    if w in [
        "sold", "profit", "equity", "wealth", "deal", "closed", "cash", "million", "win", "huge",
        "investment", "roi", "income", "buyer", "seller", "contract", "escrow", "appraisal",
        "closing", "mortgage", "financing", "capital", "off-market", "portfolio", "assets",
        "wealthy", "rich", "save", "money", "check", "bank", "deposit", "funding", "commission", "revenue"
    ]:
        return "&H00FF00&", "\\fscx220\\fscy220\\t(0,200,\\fscx120\\fscy120)"

    # 2. URGENCY, WARNING & SCARCITY (Bright Red + Shaking Effect)
    if w in [
        "listed", "drop", "warning", "stop", "alert", "urgent", "danger", "now", "limited",
        "hurry", "fast", "mistake", "never", "avoid", "risk", "deadline", "last", "chance",
        "expired", "don't", "wait", "scary", "broke", "lost", "fail", "caution", "hidden", "secret"
    ]:
        return "&H0000FF&", "\\fscx160\\fscy160\\t(0,50,\\frz5)\\t(50,100,\\frz-5)\\t(100,150,\\frz0)"

    # 3. LUXURY & INTERIORS (Gold + Elegant Grow)
    if w in [
        "luxury", "tips", "dream", "stunning", "mansion", "exclusive", "view", "penthouse", "modern",
        "renovated", "kitchen", "bathroom", "pool", "backyard", "location", "realtor", "broker",
        "gorgeous", "beautiful", "custom", "granite", "marble", "spa", "deck", "estate",
        "design", "lifestyle", "elite", "prime", "classic", "updated", "master", "suite", "amenities"
    ]:
        return "&H00D7FF&", "\\fscx200\\fscy200\\t(0,250,\\fscx115\\fscy115)"

    # 4. PROPERTY & STRUCTURE (Cyan + Punchy Tilt)
    if w in [
        "build", "strategy", "grow", "buy", "sell", "construction", "material", "move", "find", "search",
        "negotiate", "leads", "marketing", "rent", "lease", "flip", "renovate", "upgrade",
        "house", "home", "property", "land", "unit", "keys", "door", "step", "start", "condo", "townhouse"
    ]:
        return "&HFFFF00&", "\\frz-8\\fscx130\\fscy130\\t(0,150,\\frz0)"

    # 5. DATA & NUMBERS (Light Blue + Static Bold Highlight)
    if w in [
        "market", "data", "stats", "percent", "rate", "interest", "numbers", "tax", "facts",
        "proven", "results", "guaranteed", "trust", "expert", "local", "history", "years",
        "value", "price", "cost", "fee", "points", "math", "analysis", "inventory", "comps"
    ]:
        return "&HFFCC00&", "\\fscx140\\fscy140\\b1"

    # DEFAULT ACTIVE COLOR (Cyan)
    return "&H00FFFF&", ""


# ================= 5. PROCESSING LOGIC =================

def count_syllables(word: str) -> int:
    word = word.lower().strip(".,!?;:\"")
    if len(word) <= 3:
        return 1
    count = len(re.findall(r'[aeiouy]+', word))
    if word.endswith('e'):
        count -= 1
    return max(1, count)


def apply_bicep_style_to_text(text: str, total_duration_ms: int) -> str:
    if not text:
        return ""

    # --- 1. CLEANING ---
    text = text.replace("\u2018", "'").replace("\u2019", "'").replace("`", "'")
    text = text.replace(",,", "")
    text = text.replace("\\n", " ").replace("\\N", " ").replace("\n", " ").replace("\r", " ")
    text = text.replace("\xa0", " ")
    text = re.sub(r"(\w+)\s*'\s*(\w+)", r"\1'\2", text)
    text = re.sub(r"(\w+)\s+n't", r"\1n't", text, flags=re.IGNORECASE)
    text = re.sub(r"(^|\s),+([A-Za-z])", r"\1\2", text)
    text = re.sub(r'\.\s*,+', ".", text)
    text = re.sub(r'\s+', ' ', text).strip()

    # --- 2. SYLLABLE-PRECISION TIMING ---
    words = text.split()
    word_syllables = [count_syllables(w) for w in words]
    total_syllables = sum(word_syllables)

    styled_chunks = []
    total_cs = total_duration_ms // 10
    current_line_chars = 0
    current_line_effect_count = 0
    current_line_normal_count = 0

    for i, word in enumerate(words):
        clean_lookup = re.sub(r"[^\w]", "", word).lower()
        color, effect = get_word_effect(clean_lookup)
        is_effect_word = color != "&H00FFFF&"

        # Syllable-weighted duration
        syl_count = word_syllables[i]
        word_weight = syl_count / (total_syllables if total_syllables > 0 else 1)
        duration = max(1, int(total_cs * word_weight))

        added_len = len(word) + (1 if current_line_chars > 0 else 0)

        # --- EFFECT WORD COLLISION GUARD ---
        force_newline = False

        if is_effect_word:
            if current_line_effect_count >= 1 and current_line_normal_count > 0:
                force_newline = True
            elif current_line_effect_count >= 2:
                force_newline = True
        else:
            if current_line_effect_count >= 2 and current_line_normal_count == 0:
                force_newline = True

        # --- LINE OVERFLOW CHECK ---
        if (current_line_chars + added_len > CHAR_LIMIT and current_line_chars > 0) or force_newline:
            # Start a new line
            styled_chunks.append("\\N")
            current_line_chars = len(word)
            current_line_effect_count = 1 if is_effect_word else 0
            current_line_normal_count = 0 if is_effect_word else 1
        elif current_line_chars == 0 and len(word) > CHAR_LIMIT:
            # Single word too long — place it alone, mark line as full
            current_line_chars = CHAR_LIMIT
            if is_effect_word:
                current_line_effect_count += 1
            else:
                current_line_normal_count += 1
        else:
            # Normal accumulation on current line
            current_line_chars += added_len
            if is_effect_word:
                current_line_effect_count += 1
            else:
                current_line_normal_count += 1

        # --- APPLY STYLE ---
        if is_effect_word:
            styled_chunks.append(f"{{\\1c{color}{effect}}}{word.upper()}{{\\r}}")
        else:
            styled_chunks.append(f"{{\\k{duration}}}{word}{{\\r}}")

    # --- JOINING & CLEANUP ---
    result = " ".join(styled_chunks)
    result = result.replace(" \\N ", "\\N").replace("\\N ", "\\N").replace(" \\N", "\\N")
    return result


def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg Error: {e.stderr}")
        raise Exception(f"FFmpeg failed: {e.stderr}")


def get_video_dimensions(video_path: str) -> Tuple[int, int]:
    cmd = [FFPROBE_BIN, '-v', 'error', '-select_streams', 'v:0',
           '-show_entries', 'stream=width,height', '-of', 'csv=p=0', video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    dim = result.stdout.strip().split(',')
    return (int(dim[0]), int(dim[1])) if len(dim) == 2 else (1080, 1920)


def chunk_words_dynamic(whisper_segments, char_limit=CHAR_LIMIT):
    all_words = []
    for segment in whisper_segments:
        if 'words' in segment:
            all_words.extend(segment['words'])

    glued_words = []
    i = 0
    while i < len(all_words):
        curr = all_words[i]
        curr['word'] = curr['word'].strip().capitalize()
        if i + 1 < len(all_words):
            nxt = all_words[i + 1]
            if re.fullmatch(r"[%°$]|degrees|percent|units", nxt['word'].strip().lower()):
                curr['word'] += nxt['word'].strip()
                curr['end'] = nxt['end']
                i += 1
        glued_words.append(curr)
        i += 1

    bursts = []
    current_chunk = []
    current_char_count = 0

    for w in glued_words:
        word_text = w['word']
        added_len = len(word_text) + (1 if current_chunk else 0)

        if current_char_count + added_len > char_limit and current_chunk:
            bursts.append(create_ssa_event(current_chunk))
            current_chunk = []
            current_char_count = 0
            added_len = len(word_text)

        current_chunk.append(w)
        current_char_count += added_len

    if current_chunk:
        bursts.append(create_ssa_event(current_chunk))

    return bursts


def create_ssa_event(chunk):
    start_ms = int(chunk[0]['start'] * 1000)
    end_ms = int(chunk[-1]['end'] * 1000)

    full_line_text = ""
    for w in chunk:
        display_word = w['word']
        duration_cs = max(1, int((w['end'] - w['start']) * 100))
        color, effect = get_word_effect(display_word)
        full_line_text += f"{{\\1c{color}{effect}\\k{duration_cs}}}{display_word}{{\\r}} "

    return pysubs2.SSAEvent(start=start_ms, end=end_ms, text=full_line_text.strip())


def fix_truncated_last_events(subs: pysubs2.SSAFile, min_ms_per_word: int = 350) -> pysubs2.SSAFile:
    if not subs.events:
        return subs

    subs.events.sort(key=lambda e: e.start)

    for i, event in enumerate(subs.events):
        raw_text = re.sub(r"\{[^}]*\}", "", event.text)
        raw_text = raw_text.replace("\\N", " ").replace("\\n", " ")
        words = [w for w in raw_text.split() if w.strip()]
        word_count = len(words)

        if word_count == 0:
            continue

        current_duration = event.end - event.start
        required_duration = word_count * min_ms_per_word

        if current_duration >= required_duration:
            continue

        needed_extra = required_duration - current_duration

        if i + 1 < len(subs.events):
            next_start = subs.events[i + 1].start
            max_extension = next_start - event.end - 1

            if max_extension <= 0:
                new_start = event.end
                new_end = min(event.end + required_duration, next_start - 1)
                if new_end > new_start:
                    overflow_text = " ".join(words)
                    new_event = pysubs2.SSAEvent(
                        start=new_start,
                        end=new_end,
                        text=apply_bicep_style_to_text(overflow_text, new_end - new_start)
                    )
                    subs.events.insert(i + 1, new_event)
            else:
                extension = min(needed_extra, max_extension)
                event.end += extension
        else:
            event.end += needed_extra
            logger.info(
                f"Extended subtitle event [{i}] by {needed_extra}ms "
                f"— was {current_duration}ms, now {event.end - event.start}ms"
            )

    return subs


def burn_dynamic_captions(video_path: str, subs: pysubs2.SSAFile, out_path: str):
    # Style for Video 1 (Larger, Bottom-Center)
    style_v1 = pysubs2.SSAStyle(
        fontname="Montserrat ExtraBold",
        fontsize=120,
        primarycolor=pysubs2.Color(255, 255, 0),    # Yellow when spoken
        secondarycolor=pysubs2.Color(255, 255, 255),# <--- ADD THIS: White initially
        bold=True,
        alignment=2,
        outline=4.0,
        backcolor=pysubs2.Color(0, 0, 0, 180),      # Match original shadow
        marginv=100
    )

    # Style for Video 2 (Original, Middle-Center)
    style_v2 = pysubs2.SSAStyle(
        fontname="Montserrat ExtraBold",
        fontsize=85,
        primarycolor=pysubs2.Color(255, 255, 0),    # Yellow when spoken
        secondarycolor=pysubs2.Color(255, 255, 255),# <--- ADD THIS: White initially
        bold=True,
        alignment=5,
        outline=4.0,
        backcolor=pysubs2.Color(0, 0, 0, 180),      # Match original shadow
        marginv=150
    )
    # ... rest of the code

    subs.styles["V1Style"] = style_v1
    subs.styles["V2Style"] = style_v2
    subs.info["PlayResX"], subs.info["PlayResY"] = 1080, 1920

    ass_path = os.path.join(tempfile.gettempdir(), f"sub_{uuid.uuid4().hex}.ass")
    subs.save(ass_path)

    clean_ass = ass_path.replace("\\", "/").replace(":", "\\:")

    video_dur_str = run_cmd([
        FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", video_path
    ])
    video_dur_s = float(video_dur_str.strip())

    last_sub_end_s = max(e.end for e in subs.events) / 1000.0
    extra_s = max(0.0, last_sub_end_s - video_dur_s)

    if extra_s > 0.05:
        logger.info(f"Extending video by {extra_s:.2f}s to cover remaining subtitle words")
        padded_path = video_path.replace(".mp4", "_padded.mp4")
        run_cmd([
            FFMPEG_BIN, "-y", "-i", video_path,
            "-vf", f"tpad=stop_mode=clone:stop_duration={extra_s:.3f}",
            "-af", f"apad=pad_dur={extra_s:.3f}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac", padded_path
        ])
        source_path = padded_path
    else:
        source_path = video_path
        padded_path = None

    cmd = [
        FFMPEG_BIN, "-y", "-i", source_path,
        "-vf", f"subtitles='{clean_ass}':force_style='MarginL=250,MarginR=250,WrapStyle=2'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-c:a", "copy", out_path
    ]
    run_cmd(cmd)

    if os.path.exists(ass_path):
        os.remove(ass_path)
    if padded_path and os.path.exists(padded_path):
        os.remove(padded_path)


def run_cap_logic_bicep(payload: dict):
    job_id = payload.get("job_id", str(uuid.uuid4()))
    tmp_dir = tempfile.mkdtemp(dir=TMP_ROOT)
    callback_url = payload.get("callback_url")

    v1_dur = 0.0
    script_id = payload.get("script_id", "")
    script_hook = payload.get("script_hook", "")
    caption = payload.get("caption", "")
    thumbnail_url = payload.get("thumbnail_url", "")
    youtube_title = payload.get("youtube_title", "")

    try:
        v1_url = payload.get("video1_url")
        v2_url = payload.get("video2_url")
        s1_url = payload.get("subtitle1_url")
        s2_url = payload.get("subtitle2_url")

        if not all([v1_url, v2_url, s1_url, s2_url]):
            raise ValueError("Missing required video or subtitle URLs in payload")

        v1_path = os.path.join(tmp_dir, "v1.mp4")
        v2_path = os.path.join(tmp_dir, "v2.mp4")

        for url, path in [(v1_url, v1_path), (v2_url, v2_path)]:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            with open(path, 'wb') as f:
                f.write(r.content)

        def get_styled_heygen_subs(url):
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            subs = pysubs2.SSAFile.from_string(r.text)
            for event in subs.events:
                line_duration = event.end - event.start
                raw_text = re.sub(r"\{.*?\}", "", event.text)
                event.text = apply_bicep_style_to_text(raw_text, line_duration)
            subs = fix_truncated_last_events(subs, min_ms_per_word=MIN_MS_PER_WORD)
            return subs

        logger.info(f"[{job_id}] Processing HeyGen subtitles with Bicep styles...")
        subs1 = get_styled_heygen_subs(s1_url)
        subs2 = get_styled_heygen_subs(s2_url)

        # === ADD THE NEW LOGIC HERE ===

        # 1. Assign unique style names to the events
        for event in subs1.events:
            event.style = "V1Style"

        for event in subs2.events:
            event.style = "V2Style"

        # ==============================

        # Concatenate Videos
        concat_path = os.path.join(tmp_dir, "concat.mp4")
        w, h = get_video_dimensions(v1_path)

        f_complex = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[v0];"
            f"[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[v1];"
            f"[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[outv][outa]"
        )

        logger.info(f"[{job_id}] Merging videos...")
        run_cmd([FFMPEG_BIN, "-y", "-i", v1_path, "-i", v2_path,
                 "-filter_complex", f_complex,
                 "-map", "[outv]", "-map", "[outa]", concat_path])

        # Get duration of video 1 in ms
        v1_dur_str = run_cmd([
            FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", v1_path
        ])
        v1_dur_ms = int(float(v1_dur_str.strip()) * 1000)

        # ── FIX 1: Hard-clamp ALL subs1 events to stay within video 1's boundary ──
        # Runs ONCE — leave a clean 40ms gap before video 2 starts
        if subs1.events:
            subs1.events.sort(key=lambda e: e.start)
            hard_limit = v1_dur_ms - 40
            for event in subs1.events:
                if event.end > hard_limit:
                    event.end = hard_limit
                # If the start itself overshot (edge case from fix_truncated), pull it back
                if event.start >= hard_limit:
                    event.start = max(0, hard_limit - 80)
                    event.end = hard_limit

        # Shift subs2 timestamps forward by video 1's duration
        for event in subs2.events:
            event.start += v1_dur_ms
            event.end += v1_dur_ms

        # Merge into one subtitle file
        final_subs = subs1
        final_subs.events.extend(subs2.events)

        # Burn captions
        final_video = os.path.join(tmp_dir, "final.mp4")
        logger.info(f"[{job_id}] Burning cleaned captions...")
        burn_dynamic_captions(concat_path, final_subs, final_video)

        # Upload to Cloudinary
        logger.info(f"[{job_id}] Uploading final merged video...")
        up = cloudinary.uploader.upload(
            final_video,
            resource_type="video",
            folder="real_estate_results",
            public_id=f"bicep_{job_id}"
        )

        video_url = up.get("secure_url")
        logger.info(f"[{job_id}] Upload successful: {video_url}")

        # Send Success Webhook
        if callback_url:
            response_data = {
                "job_id": job_id,
                "status": "success",
                "video_url": video_url,
                "script_id": script_id,
                "script_hook": script_hook,
                "caption": caption,
                "thumbnail_url": thumbnail_url,
                "youtube_title": youtube_title,
                "video_merged_duration": v1_dur
            }
            logger.info(f"[{job_id}] Sending callback to {callback_url}")
            cb_res = requests.post(callback_url, json=response_data, timeout=30)
            logger.info(f"[{job_id}] Callback status: {cb_res.status_code}")

    except Exception as e:
        logger.error(f"[{job_id}] CRITICAL ERROR in Bicep: {str(e)}", exc_info=True)
        if callback_url:
            try:
                requests.post(callback_url, json={
                    "job_id": job_id,
                    "status": "error",
                    "message": str(e),
                    "script_id": script_id,
                    "script_hook": script_hook,
                    "youtube_title": youtube_title
                }, timeout=10)
                logger.info(f"[{job_id}] Error callback sent to {callback_url}")
            except Exception as cb_e:
                logger.error(f"[{job_id}] Failed to send error callback: {cb_e}")

    finally:
        if 'tmp_dir' in locals() and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            logger.info(f"[{job_id}] Temporary directory cleaned up")
        import gc
        gc.collect()
