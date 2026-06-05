# 🎬 Video Processing Suite

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-green.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![Cloudinary](https://img.shields.io/badge/Cloudinary-Integrated-orange.svg)](https://cloudinary.com/)

> **Enterprise-grade video processing API with AI-powered captioning, dynamic word effects, and Cloudinary integration**

## ✨ Features

### 🎯 Multiple Processing Pipelines

| Pipeline | Description | Best For |
|----------|-------------|----------|
| **CAP** | Basic captions with box styling | Simple, readable subtitles |
| **CAPP** | Social media uppercase captions | Instagram, TikTok, Shorts |
| **BICEP** | Dynamic word-by-word effects | Premium content, real estate |
| **Worker** | Timeline-based video builder | Complex video assembly |

### 🎨 Advanced Caption Styling

- **Word-by-word coloring** based on meaning (success, urgency, luxury)
- **Syllable-aware timing** for natural karaoke effect
- **Animation effects** (pop, shake, grow, tilt, highlight)
- **Multi-language support** with Whisper AI
- **ASS/SSA subtitle format** for professional styling

### 🚀 Technical Capabilities

- **Async processing** with background tasks
- **Cloudinary CDN** upload with chunked upload (3-6MB chunks)
- **Webhook callbacks** with retry logic
- **Docker ready** with multi-stage builds
- **Horizontal scaling** support with Redis/Celery
- **Health checks** and monitoring endpoints

## 📋 Prerequisites

- Python 3.11+
- FFmpeg 4.0+
- Docker & Docker Compose (optional)
- Cloudinary account (free tier available)

## 🚀 Quick Start

### Local Development

```bash
# Clone repository
git clone https://github.com/BilalKhan563/video-processing-suite.git
cd video-processing-suite

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your Cloudinary credentials

# Run the server
python -m app.main
# or
uvicorn app.main:app --reload --port 8000
