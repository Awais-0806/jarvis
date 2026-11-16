FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git cmake build-essential ffmpeg libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth 1 --branch v1.5.4 https://github.com/ggerganov/whisper.cpp.git /whisper
WORKDIR /whisper
RUN cmake -B build -DBUILD_SHARED_LIBS=OFF && cmake --build build -j --config Release --target whisper-cli
RUN sh ./models/download-ggml-model.sh base.en

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m piper.download_voices en_US-lessac-medium --download-dir /voices

COPY . .

RUN groupadd --system --gid 10001 jarvis && useradd --system --uid 10001 --gid jarvis --create-home jarvis
USER 10001

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]