# Single image: builds the React dashboard, then serves it + the API from one Python process (CPU only).
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 CONVEYOR_DB_URL=sqlite:////data/conveyor.db
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY models/ models/
COPY data/vision/samples/ data/vision/samples/
COPY --from=web /web/dist frontend/dist
RUN mkdir -p /data
WORKDIR /app/backend
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
