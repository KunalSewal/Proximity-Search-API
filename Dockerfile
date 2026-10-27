# Proximity Search API (Flask + gunicorn)
#
#   docker build -t proximity-api .                      -> runtime image
#   docker build --target test -t proximity-api:test .   -> runtime + pytest + tests
#   (stages: builder -> runtime, builder -> testdeps, runtime + testdeps venv -> test)
#   docker run --rm proximity-api:test                   -> run the test suite

# ---------- builder: install dependencies into a self-contained venv ----------
FROM python:3.12-slim AS builder

# Generous timeout/retries: downloads from PyPI timed out on a slow connection.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copied on its own so this layer stays cached until the dependencies change.
# The cache mount keeps downloaded wheels across builds without putting them in the image.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# ---------- testdeps: builder venv + pytest (only rebuilt when requirements change) ----------
FROM builder AS testdeps
RUN --mount=type=cache,target=/root/.cache/pip pip install pytest

# ---------- runtime: slim image with the venv and the app only ----------
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    WORKERS=4 \
    THREADS=2 \
    LOCATIONS_CSV=/app/data/locations.csv \
    LINKS_DIR=/app/links

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app.py engine.py gunicorn.conf.py ./
COPY data/ data/
COPY links/ links/

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=2)"]

# Exec form: gunicorn runs as PID 1 and receives SIGTERM from `docker stop` directly.
# Bind address, workers and threads come from PORT / WORKERS / THREADS via gunicorn.conf.py.
CMD ["gunicorn", "app:app"]

# ---------- test: runtime + the venv that also has pytest + test suite ----------
FROM runtime AS test
COPY --from=testdeps /opt/venv /opt/venv
COPY tests/ tests/
# /app is root-owned and read-only for appuser, so pytest's cache plugin is switched off.
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
