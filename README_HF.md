# ГУСЬ - Video Pipeline
# Деплой на HuggingFace Spaces (Free GPU/ZeroGPU)

name: goose-video-pipeline
sdk: docker
app_port: 7860
pinned: false

[env]
PORT=7860
HOST=0.0.0.0
PYTHONUNBUFFERED=1
PYTHONIOENCODING=utf-8
