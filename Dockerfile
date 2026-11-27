# One image for all app services (web, worker, beat, migrate); compose.yaml
# chooses the command. Data lives in volumes, not in the image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# CPU-only PyTorch for sentence-transformers. Without this, pip would pull the
# CUDA build (several GB) that cannot be used in this container anyway.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
