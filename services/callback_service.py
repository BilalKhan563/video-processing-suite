import requests
import logging

logger = logging.getLogger(__name__)


def send_callback(callback_url: str, data: dict, job_id: str, max_retries: int = 3) -> bool:
    """Send callback with retry logic"""
    if not callback_url:
        return False

    for attempt in range(max_retries):
        try:
            response = requests.post(callback_url, json=data, timeout=30)
            if response.status_code == 200:
                logger.info(f"[{job_id}] Callback sent successfully")
                return True
        except Exception as e:
            logger.warning(f"[{job_id}] Callback attempt {attempt + 1} failed: {e}")
            time.sleep(2 ** attempt)

    return False