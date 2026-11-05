FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ANKI_DATA_DIR=/data

WORKDIR /srv
COPY pyproject.toml ./
RUN pip install --no-cache-dir "anki==26.9.4" "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic-settings>=2.4"
COPY app ./app

RUN useradd --create-home --uid 1000 anki && mkdir -p /data && chown anki /data
USER anki
VOLUME /data
EXPOSE 8000

# UN SOLO worker: la collezione Anki va aperta da un unico processo.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
