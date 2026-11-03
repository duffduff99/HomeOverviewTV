FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONFIG_DIR=/config \
    MUSIC_DIR=/music \
    PORT=8080

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY housetv ./housetv
COPY web ./web
COPY themes ./themes
COPY config/config.example.yaml ./config/config.example.yaml

RUN useradd --system --uid 1000 --home /app housetv \
    && mkdir -p /config /music && chown housetv /config /music
USER housetv

EXPOSE 8080
VOLUME ["/config", "/music"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4)"

ENTRYPOINT ["python", "-m", "housetv"]
