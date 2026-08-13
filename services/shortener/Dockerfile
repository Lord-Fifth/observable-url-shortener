FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/service/app

WORKDIR /service

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt \
    && addgroup --system appuser \
    && adduser --system --ingroup appuser --no-create-home appuser

COPY --chown=appuser:appuser app ./app

USER appuser
EXPOSE 8080
STOPSIGNAL SIGTERM

CMD ["python", "-m", "uvicorn", "shortener.main:app", "--host", "0.0.0.0", "--port", "8080"]

