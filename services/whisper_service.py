import threading
import whisper

_whisper_model = None
_model_lock = threading.Lock()

def get_whisper_model(model_size: str = "tiny"):
    """Thread-safe Whisper model loader"""
    global _whisper_model
    with _model_lock:
        if _whisper_model is None:
            print(f"🚀 Loading Whisper Model ({model_size})...")
            _whisper_model = whisper.load_model(
                model_size,
                device="cpu",
                download_root="/tmp/whisper_models"
            )
            print("✅ Whisper Model loaded")
    return _whisper_model