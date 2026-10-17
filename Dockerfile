# ICEFLOW - single container serving both halves.
#
# The frontend is built and then served BY the API, so the deployed system is same-origin. That
# removes two whole classes of problem at once: no CORS configuration, and no need to tell the
# bundle where its backend lives. One service, one URL, one thing to keep running.
#
#   docker build -t ICEFLOW .
#   docker run -p 8000:8000 ICEFLOW      ->  http://localhost:8000

# ---------------------------------------------------------------------------- frontend build
FROM node:20-slim AS frontend

WORKDIR /build
# Copy manifests first so the dependency layer is cached independently of source changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# No VITE_API_BASE_URL: the API serves this bundle, so relative paths are correct.
RUN npm run build

# ---------------------------------------------------------------------------- runtime
FROM python:3.11-slim AS runtime

# Faster start-up, no .pyc clutter, and unbuffered logs so the platform sees them live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY models/metrics.json ./models/metrics.json
COPY --from=frontend /build/dist ./frontend/dist

# SQLite lives here. On a platform with an ephemeral filesystem this is wiped on redeploy, which
# is acceptable: voyages are demonstrations, not records. Mount a volume at /app/data to keep them.
RUN mkdir -p data

# The trained model binaries are not in the image. They are optional by design - the physics path
# never touches them - and building them would add four minutes and ~13 MB to every image build.
# Run `python -m scripts.train` inside a running container if you want the radar classifier.

EXPOSE 8000

# One worker, deliberately.
#
# Voyage engines are held in process memory, so a second worker would answer /step and the voyage
# WebSocket from a process that has never heard of that voyage. Scaling this properly means moving
# voyage state into Redis; until then, one worker is correct rather than merely convenient.
CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
