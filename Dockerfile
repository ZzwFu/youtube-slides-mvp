FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir yt-dlp

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
ENV PYTHONPATH=/app/src

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -m youtube_slides_mvp.cli healthcheck || exit 1

CMD ["python", "-m", "youtube_slides_mvp.cli", "healthcheck"]
