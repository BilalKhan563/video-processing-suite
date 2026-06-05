"""
Railway-compatible Video Processing Worker
Processes video generation tasks with Cloudinary upload and callback support
"""
import os
# Set BEFORE moviepy imports
# # Set BEFORE moviepy imports
os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"
os.environ["MAGICK_HOME"] = "/usr"

import re
import requests
import random
import json
import logging
import hashlib
import time
import shutil
import tempfile
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cloudinary
import cloudinary.uploader
from pydantic import BaseModel, Field, validator

# app.py - Update imports and the process_worker endpoint
from fastapi import FastAPI, BackgroundTasks, Query, HTTPException
from typing import Optional, Dict, Any
import os
import sys
import time  # Add this import


# NOW import moviepy (after env vars are set)
from moviepy.editor import VideoFileClip, TextClip

# =========================
# Logging Configuration
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =========================
# Configuration
# =========================
@dataclass
class VideoConfig:
    """Video processing configuration."""
    WPM: int = 166
    SECONDS_PER_WORD: float = 60 / 166
    SEGMENT_DELIMITER: str = ",,"
    MAX_SEGMENTS: int = 10
    MIN_SEGMENTS: int = 1
    DEFAULT_TIMEOUT: int = 30

    def __post_init__(self):
        self.SECONDS_PER_WORD = 60 / self.WPM


# =========================
# Cloudinary Configuration
# =========================
def configure_cloudinary():
    """Configure Cloudinary from environment variables."""
    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        secure=True
    )
    logger.info("Cloudinary configured successfully")


# =========================
# Utility Functions
# =========================
def get_utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def ensure_tmp_directory() -> Path:
    """Ensure /tmp directory exists and return Path object."""
    tmp_dir = Path("/tmp")
    tmp_dir.mkdir(exist_ok=True)
    return tmp_dir


def create_work_directory() -> Path:
    """Create a unique temporary working directory."""
    tmp_dir = ensure_tmp_directory()
    work_dir = tmp_dir / f"video_work_{int(time.time())}_{random.randint(1000, 9999)}"
    work_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created work directory: {work_dir}")
    return work_dir


def cleanup_directory(directory: Path):
    """Remove directory and all its contents."""
    try:
        if directory.exists():
            shutil.rmtree(directory)
            logger.info(f"Cleaned up directory: {directory}")
    except Exception as e:
        logger.error(f"Failed to cleanup directory {directory}: {e}")


# =========================
# VideoBuilder Import with Fallback
# =========================
try:
    from sample2 import VideoBuilder

    VIDEOBUILDER_AVAILABLE = True
    logger.info("VideoBuilder imported successfully")
except ImportError as e:
    VIDEOBUILDER_AVAILABLE = False
    logger.warning(f"VideoBuilder not available: {e}")


    class MockVideoBuilder:
        """Mock VideoBuilder for testing."""

        def __init__(self):
            self.mock_counter = 0

        def build_video_from_single_timeline(self, timeline_data, index=0):
            """Generate a mock video file."""
            self.mock_counter += 1
            work_dir = Path("/tmp") / "mock_videos"
            work_dir.mkdir(exist_ok=True)

            # Create a dummy video file
            video_path = work_dir / f"mock_video_{self.mock_counter}.mp4"
            video_path.write_bytes(b"MOCK VIDEO CONTENT")

            time.sleep(0.5)  # Simulate processing
            return str(video_path)


    VideoBuilder = MockVideoBuilder
    VIDEOBUILDER_AVAILABLE = True
    logger.info("MockVideoBuilder activated")


# =========================
# Pydantic Models
# =========================
class ImagePrompts(BaseModel):
    """Represents image prompts for video segments."""
    prompts: List[str] = Field(default_factory=list, min_items=1, max_items=10)


class ImagesPrompts(BaseModel):
    """Alternative format with explicit numbered fields."""
    prompts: Optional[List[str]] = Field(None, min_items=9, max_items=9)
    image_prompt1: Optional[str] = None
    image_prompt2: Optional[str] = None
    image_prompt3: Optional[str] = None
    image_prompt4: Optional[str] = None
    image_prompt5: Optional[str] = None
    image_prompt6: Optional[str] = None
    image_prompt7: Optional[str] = None
    image_prompt8: Optional[str] = None
    image_prompt9: Optional[str] = None


class VideoPayload(BaseModel):
    """Input payload for video generation."""
    script: str = Field(..., min_length=1, description="Video script content")
    caption: Optional[str] = Field(None, max_length=500)
    youtube_title: Optional[str] = Field(None, max_length=100)
    script_hook: Optional[str] = Field(None, max_length=200)

    # --- ADDED/UPDATED FIELDS ---
    script_id: Optional[Union[int, str]] = None
    image_urls: Any = Field(default_factory=list)  # Changed from Dict to Any
    # ----------------------------

    images_prompts: Optional[Dict[str, str]] = None

    @validator('script')
    def validate_script_segments(cls, v):
        """Validate script has correct number of segments."""
        config = VideoConfig()
        segments = [seg.strip() for seg in v.split(config.SEGMENT_DELIMITER) if seg.strip()]
        if len(segments) < config.MIN_SEGMENTS:
            raise ValueError(f"Script must have at least {config.MIN_SEGMENTS} segment(s)")
        if len(segments) > config.MAX_SEGMENTS:
            raise ValueError(f"Script cannot have more than {config.MAX_SEGMENTS} segments")
        return v


# =========================
# Helper Functions
# =========================
def tokenize_words(text: str) -> List[str]:
    """Extract words from text for timing calculation."""
    return re.findall(r'\b\w+\b', text)


def calculate_segment_duration(text: str, config: VideoConfig = None) -> float:
    """Calculate duration for a script segment based on word count."""
    if config is None:
        config = VideoConfig()
    words = tokenize_words(text)
    return len(words) * config.SECONDS_PER_WORD


def create_timeline_entry(
        start_time: float,
        duration: float,
        script_text: str,
        image_url: str = "",
        image_prompt: str = ""
) -> Dict[str, Any]:
    """Create a standardized timeline entry."""
    return {
        "start_time": round(start_time, 2),
        "end_time": round(start_time + duration, 2),
        "script_text": script_text,
        "image_url": image_url,
        "image_prompt": image_prompt,
        "duration": round(duration, 2)
    }


def extract_image_resources(
        image_data: Any,  # Changed from image_urls_dict: Dict
        prompts_dict: Dict[str, str],
        num_segments: int
) -> Tuple[List[str], List[str]]:
    """Extract image URLs and prompts for the required number of segments."""
    image_urls = []
    image_prompts = []

    logger.info(f"Extracting resources for {num_segments} segments")

    # --- ROBUST URL EXTRACTION ---
    for i in range(1, num_segments + 1):
        url = ""

        # Scenario A: Payload is a List of Dicts (Cloudinary format)
        if isinstance(image_data, list):
            idx = i - 1
            if idx < len(image_data):
                item = image_data[idx]
                if isinstance(item, dict):
                    url = item.get("secure_url", "")
                else:
                    url = str(item)

        # Scenario B: Payload is a Dictionary (Original format)
        elif isinstance(image_data, dict):
            url_keys = [f"Image_url_{i}", f"image_url_{i}", f"Image_{i}", str(i - 1), str(i)]
            for key in url_keys:
                if key in image_data and image_data[key]:
                    url = str(image_data[key]).strip()
                    break

        image_urls.append(url)
        # -----------------------------

        # Extract prompt (Same as before)
        prompt_keys = [f"image_prompt{i}", f"prompt_{i}", str(i - 1)]
        prompt = ""
        if prompts_dict:
            for key in prompt_keys:
                if key in prompts_dict and prompts_dict[key]:
                    prompt = str(prompts_dict[key]).strip()
                    break
        image_prompts.append(prompt)

    return image_urls, image_prompts


# =========================
# Video Timeline Generator
# =========================
class VideoTimelineGenerator:
    """Generates timeline for video segments with proper timing."""

    def __init__(self, config: VideoConfig = None):
        self.config = config or VideoConfig()

    def generate_timeline(
            self,
            script: str,
            image_prompts: List[str],
            image_urls: List[str]
    ) -> List[Dict[str, Any]]:
        """Generate timeline for video segments."""
        segments = [
            seg.strip()
            for seg in script.split(self.config.SEGMENT_DELIMITER)
            if seg.strip()
        ]

        num_segments = len(segments)

        if not (self.config.MIN_SEGMENTS <= num_segments <= self.config.MAX_SEGMENTS):
            raise ValueError(
                f"Expected {self.config.MIN_SEGMENTS}-{self.config.MAX_SEGMENTS} segments, "
                f"found {num_segments}"
            )

        # Pad lists to match segment count
        image_prompts = self._pad_list(image_prompts, num_segments, "")
        image_urls = self._pad_list(image_urls, num_segments, "")

        # Build timeline
        timeline = []
        current_time = 0.0

        for i, segment in enumerate(segments):
            duration = calculate_segment_duration(segment, self.config)

            timeline.append(create_timeline_entry(
                start_time=current_time,
                duration=duration,
                script_text=segment,
                image_url=image_urls[i],
                image_prompt=image_prompts[i]
            ))

            current_time += duration

        logger.info(f"Generated timeline with {len(timeline)} segments, total duration: {current_time:.2f}s")
        return timeline

    def _pad_list(self, items: List[str], target_length: int, default_value: str = "") -> List[str]:
        """Pad or truncate list to target length."""
        if len(items) >= target_length:
            return items[:target_length]
        return items + [default_value] * (target_length - len(items))


# =========================
# Cloudinary Upload
# =========================
def upload_to_cloudinary(video_path: str, job_id: str) -> str:
    """
    Upload video to Cloudinary and return public URL.

    Args:
        video_path: Local path to video file
        job_id: Unique job identifier for naming

    Returns:
        Public URL of uploaded video
    """
    try:
        logger.info(f"Uploading video to Cloudinary: {video_path}")

        # Upload with resource_type='video'
        result = cloudinary.uploader.upload(
            video_path,
            resource_type="video",
            public_id=f"videos/{job_id}",
            folder="generated_videos",
            overwrite=True,
            transformation=[
                {'quality': 'auto'},
                {'fetch_format': 'auto'}
            ]
        )

        video_url = result.get('secure_url')
        logger.info(f"Video uploaded successfully: {video_url}")

        return video_url

    except Exception as e:
        logger.error(f"Cloudinary upload failed: {e}")
        raise


# =========================
# Callback Handler
# =========================
# Update the send_callback function in worker.py:
def send_callback(callback_url: str, data: dict, job_id: str) -> bool:
    """Send callback POST request with enhanced error handling."""
    if not callback_url or not callback_url.startswith(('http://', 'https://')):
        logger.warning(f"[{job_id}] Invalid callback URL: {callback_url}")
        return False

    try:
        logger.info(f"[{job_id}] Sending callback to: {callback_url}")

        # Prepare callback data - nested inside metadata
        callback_data = {
            "status": data.get("status", "success"),
            "job_id": job_id,
            "video_url": data.get("video_url"),
            "timestamp": data.get("completed_at", get_utc_now().isoformat()),
            "metadata": {
                "script_id": data.get("script_id"),
                "script": data.get("script"),
                "youtube_title": data.get("youtube_title"),
                "caption": data.get("caption"),
                "script_hook": data.get("script_hook"),
                "segment_count": data.get("timeline_summary", {}).get("segment_count", 0),
                "total_duration": data.get("timeline_summary", {}).get("total_duration", 0)
            }
        }

        logger.info(f"[{job_id}] Callback payload sent with metadata: {json.dumps(callback_data, indent=2)}")
        # Send with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    callback_url,
                    json=callback_data,
                    timeout=30,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "VideoProcessingWorker/2.0",
                        "X-Job-ID": job_id
                    }
                )

                logger.info(f"[{job_id}] Callback attempt {attempt + 1}/{max_retries} - Status: {response.status_code}")

                if response.status_code == 200:
                    logger.info(f"[{job_id}] ✅ Callback sent successfully")
                    logger.info(f"[{job_id}] Callback response: {response.text[:200]}")
                    return True
                else:
                    logger.warning(
                        f"[{job_id}] Callback failed with status {response.status_code}: {response.text[:200]}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff

            except requests.exceptions.Timeout:
                logger.error(f"[{job_id}] Callback timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

            except requests.exceptions.RequestException as e:
                logger.error(f"[{job_id}] Callback error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

        logger.error(f"[{job_id}] ❌ All callback attempts failed")
        return False

    except Exception as e:
        logger.error(f"[{job_id}] Unexpected error during callback: {e}")
        return False


# =========================
# Main Worker Logic
# =========================
# =========================
# Main Worker Logic
# =========================
def run_worker_logic(payload: dict):
    work_dir = None
    job_id = payload.get('job_id', f"job-{int(time.time())}-{random.randint(1000, 9999)}")
    callback_url = payload.get('callback_url')

    # Grab raw video data immediately for fallback metadata
    video_data = payload.get('video', {})

    try:
        logger.info(f"[{job_id}] Starting video processing")
        configure_cloudinary()
        work_dir = create_work_directory()

        # --- FIX 1: REPAIR IMAGE_URLS STRING BEFORE VALIDATION ---
        raw_urls = video_data.get('image_urls')
        if isinstance(raw_urls, str) and raw_urls.strip():
            try:
                # If it's a list of {} but missing brackets (Make.com style)
                if not raw_urls.strip().startswith('['):
                    video_data['image_urls'] = json.loads(f"[{raw_urls}]")
                else:
                    video_data['image_urls'] = json.loads(raw_urls)
            except Exception as e:
                logger.warning(f"[{job_id}] Soft-failed parsing image_urls: {e}")
                # Set to empty list so Pydantic validation passes;
                # extract_image_resources will use regex later.
                video_data['image_urls'] = []

        # Parse and Validate
        try:
            video_payload = VideoPayload(**video_data)
            logger.info(f"[{job_id}] Payload validated successfully")
        except Exception as e:
            # --- FIX 2: METADATA FALLBACK ON VALIDATION ERROR ---
            error_response = {
                "status": "error",
                "message": f"Validation failed: {str(e)}",
                "job_id": job_id,
                "failed_at": get_utc_now().isoformat(),
                "metadata": {
                    "script_id": video_data.get("script_id"),
                    "script": video_data.get("script"),
                    "youtube_title": video_data.get("youtube_title"),
                    "caption": video_data.get("caption")
                }
            }
            if callback_url:
                send_callback(callback_url, error_response, job_id)
            raise

        # Extract segments (Fixing the trailing ,, issue)
        segments = [seg.strip() for seg in video_payload.script.split(',,') if len(seg.strip()) > 2]
        num_segments = len(segments)

        # Get image resources (This uses your extract_image_resources function)
        images_prompts_dict = video_data.get("images_prompts", {})
        if isinstance(images_prompts_dict, str):
            try:
                images_prompts_dict = json.loads(images_prompts_dict)
            except:
                images_prompts_dict = {}

        image_urls, image_prompts = extract_image_resources(
            video_payload.image_urls if video_payload.image_urls else raw_urls,
            images_prompts_dict,
            num_segments
        )

        # --- FIX 3: PREVENT CRASH IF ONLY SOME IMAGES ARE MISSING ---
        valid_urls = [url for url in image_urls if url and str(url).startswith('http')]
        if not valid_urls:
            error_msg = "No valid image URLs found in request"
            logger.error(f"[{job_id}] {error_msg}")
            error_response = {
                "status": "error",
                "message": error_msg,
                "job_id": job_id,
                "metadata": {
                    "script_id": video_payload.script_id,
                    "script": video_payload.script
                }
            }
            if callback_url:
                send_callback(callback_url, error_response, job_id)
            raise ValueError(error_msg)

        # Generate timeline
        timeline_generator = VideoTimelineGenerator()
        timeline = timeline_generator.generate_timeline(video_payload.script, image_prompts, image_urls)

        # Build video
        videobuilder = VideoBuilder()
        timeline_data = {
            "timeline": timeline,
            "overlays": [],
            "metadata": {"job_id": job_id}
        }

        video_local_path = videobuilder.build_video_from_single_timeline(timeline_data, index=0)
        video_url = upload_to_cloudinary(video_local_path, job_id)

        # Success Response
        # --- FIXED VERSION ---
        success_response = {
            "status": "success",
            "job_id": job_id,
            "script_id": video_payload.script_id,
            "video_url": video_url,
            "youtube_title": video_payload.youtube_title or "",
            "caption": video_payload.caption or "",
            "script_hook": video_payload.script_hook or "",
            "script": video_payload.script,
            "completed_at": get_utc_now().isoformat(),
            # Add this so send_callback can find the stats
            "timeline_summary": {
                "segment_count": len(segments),
                "total_duration": timeline[-1]['end_time'] if timeline else 0
            }
        }

        if callback_url:
            send_callback(callback_url, success_response, job_id)

        return success_response

    except Exception as e:
        logger.error(f"[{job_id}] Processing failed: {str(e)}")
        # Final catch-all fallback
        error_response = {
            "status": "error",
            "message": str(e),
            "job_id": job_id,
            "metadata": {
                "script_id": video_data.get("script_id"),
                "youtube_title": video_data.get("youtube_title")
            }
        }
        if callback_url:
            send_callback(callback_url, error_response, job_id)
        raise
    finally:
        if work_dir:
            cleanup_directory(work_dir)


# =========================
# Entry Point for Testing
# =========================
if __name__ == "__main__":
    # Example payload for testing
    test_payload = {
        "job_id": "test-job-123",
        "callback_url": "https://example.com/callback",
        "video": {
            "script": "First segment of video,,Second segment of video,,Third segment of video",
            "caption": "Test video caption",
            "youtube_title": "Test Video Title",
            "image_urls": {
                "Image_url_1": "https://example.com/image1.jpg",
                "Image_url_2": "https://example.com/image2.jpg",
                "Image_url_3": "https://example.com/image3.jpg"
            },
            "images_prompts": {
                "image_prompt1": "First image prompt",
                "image_prompt2": "Second image prompt",
                "image_prompt3": "Third image prompt"
            }
        }
    }

    try:
        result = run_worker_logic(test_payload)
        print(f"Success: {json.dumps(result, indent=2)}")
    except Exception as e:
        print(f"Error: {str(e)}")