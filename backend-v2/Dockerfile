FROM python:3.12-slim

WORKDIR /app

# Install ffmpeg (for audio conversion in /stt) and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Force cache bust before copying source (ensures latest code is used)
ARG BUILD_DATE=now
RUN echo "Build at ${BUILD_DATE}" > /dev/null

# Copy source code
COPY . .

# Create data directory for SQLite
RUN mkdir -p /data

# Environment
ENV PORT=7860
ENV DATABASE_URL=sqlite:////data/xiaozhi.db

EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
