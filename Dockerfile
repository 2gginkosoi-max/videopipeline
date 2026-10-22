FROM pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    HF_HOME=/app/.cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаём необходимые директории
RUN mkdir -p /app/web/users /app/web/uploads /app/web/data /app/output /app/F5-TTS/out /app/temp

EXPOSE 7860

ENV PORT=7860
ENV HOST=0.0.0.0

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "7860"]
