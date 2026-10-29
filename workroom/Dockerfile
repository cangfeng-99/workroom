FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WORKROOM_MODE=server WORKROOM_DATA_DIR=/data
WORKDIR /app
COPY requirements-server.lock ./
RUN pip install --no-cache-dir -r requirements-server.lock && useradd --create-home --uid 10001 workroom && mkdir /data && chown workroom:workroom /data /app
COPY --chown=workroom:workroom . .
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "server_wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "2", "--timeout", "60", "--max-requests", "1000", "--max-requests-jitter", "50"]
