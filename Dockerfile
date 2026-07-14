FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY app /app/app

RUN pip install --upgrade pip \
    && pip install 'telethon>=1.44,<2' cryptg 'python-socks[asyncio]' python-qbittorrent

CMD ["python", "-m", "app.bot.main"]
