import subprocess
from typing import Tuple

FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

def run_cmd(cmd):
    """Run FFmpeg command with error handling"""
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise Exception(f"FFmpeg failed: {e.stderr}")

def get_video_dimensions(video_path: str) -> Tuple[int, int]:
    """Get width and height of video"""
    cmd = [FFPROBE_BIN, '-v', 'error', '-select_streams', 'v:0',
           '-show_entries', 'stream=width,height', '-of', 'csv=p=0', video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    dim = result.stdout.strip().split(',')
    return (int(dim[0]), int(dim[1])) if len(dim) == 2 else (1080, 1920)