FROM python:3.13-slim

# Flush print/log output immediately so `docker compose logs` shows it live.
ENV PYTHONUNBUFFERED=1

WORKDIR /code

# Exact versions of every package, generated on this same Linux/Python base (see README: "Updating dependencies").
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY app/ app/

RUN useradd --create-home appuser && mkdir data && chown appuser data  # pipeline writes extracted images here
USER appuser

# Default = API; compose overrides `command` for the UI service.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
