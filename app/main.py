import os
from fastapi import FastAPI, BackgroundTasks
from app.config import settings
from app.routes import cap, cappp, worker, bicep

# Set environment variables BEFORE any imports
os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"
os.environ["MAGICK_HOME"] = "/usr"

app = FastAPI(title="Railway Video Processing Suite")

# Include routers
app.include_router(cap.router, prefix="/process", tags=["CAP"])
app.include_router(cappp.router, prefix="/process", tags=["CAPP"])
app.include_router(worker.router, prefix="/process", tags=["Worker"])
app.include_router(bicep.router, prefix="/process", tags=["BICEP"])

@app.get("/")
def root():
    return {"status": "online", "message": "Video Processing Server is running"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)