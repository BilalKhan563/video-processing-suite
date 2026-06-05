import cloudinary
import cloudinary.uploader
import os

def configure_cloudinary():
    """Configure Cloudinary from environment"""
    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
        api_key=os.environ.get("CLOUDINARY_API_KEY"),
        api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
        secure=True
    )

def upload_video(video_path: str, folder: str, job_id: str = None) -> str:
    """Upload video to Cloudinary"""
    public_id = f"{folder}/{job_id}" if job_id else f"{folder}/{int(time.time())}"
    result = cloudinary.uploader.upload(
        video_path,
        resource_type="video",
        public_id=public_id,
        folder=folder
    )
    return result.get("secure_url")