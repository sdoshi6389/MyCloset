FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System libraries required by OpenCV (cv2). torch / mediapipe / basicsr all
# pull in non-headless OpenCV builds that need libGL + libglib at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for better layer caching. requirements.txt carries the
# --extra-index-url line that pulls CPU torch wheels.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Railway injects $PORT. One worker (models are large — multiple workers would
# multiply RAM); concurrency comes from threads.
CMD ["sh", "-c", "gunicorn main:app --workers 1 --threads 2 --timeout 600 --graceful-timeout 60 --keep-alive 5 --bind 0.0.0.0:${PORT:-5000}"]
