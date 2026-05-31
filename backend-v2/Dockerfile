FROM python:3.12-slim
# v2 - force rebuild

WORKDIR /app

# Install ffmpeg (for audio conversion in /stt) and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend-v2/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code from backend-v2 subdirectory
COPY backend-v2/ .

# Create data directory for SQLite
RUN mkdir -p /data

# Environment
ENV PORT=7860
ENV DATABASE_URL=sqlite:////data/xiaozhi.db

EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
