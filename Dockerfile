FROM python:3.12-slim AS source
WORKDIR /release
COPY source.zip .
RUN python -m zipfile -e source.zip /unpacked
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data APP_HOSTED=true
WORKDIR /app
COPY --from=source /unpacked/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 appuser && mkdir /data && chown appuser:appuser /data
COPY --from=source /unpacked/app ./app
COPY --from=source /unpacked/settings ./settings
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
