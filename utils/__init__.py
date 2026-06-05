"""Utility functions"""
from .logger import logger, setup_logging
from .helpers import (
    create_work_directory,
    cleanup_directory,
    get_utc_now,
    ensure_tmp_directory
)
from .text_utils import (
    escape_ffmpeg_text,
    wrap_text,
    count_syllables,
    apply_word_effect
)