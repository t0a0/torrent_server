FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY app /app/app

RUN pip install --upgrade pip \
    && pip install aiogram aiohttp-socks python-qbittorrent

CMD ["python", "-m", "app.bot.main"]
