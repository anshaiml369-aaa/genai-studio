FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user --upgrade pip && pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user . .
EXPOSE 7860
# one process: background video jobs and the public-demo counters live in memory
CMD ["uvicorn", "main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips=*"]
