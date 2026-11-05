FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ANKI_DATA_DIR=/data \
    ANKI_LOG_FORMAT=json \
    # X-Forwarded-For/-Proto valgono solo se arrivano da un proxy della rete privata
    # (nginx del servizio `web`, Traefik): così il rate limit vede l'IP vero del client
    # e un client non può fingersi un altro scrivendo l'header a mano.
    FORWARDED_ALLOW_IPS="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"

WORKDIR /srv
COPY pyproject.toml ./
RUN pip install --no-cache-dir "anki==26.9.4" "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic-settings>=2.4"
COPY app ./app
COPY scripts ./scripts

RUN useradd --create-home --uid 1000 anki && mkdir -p /data && chown anki /data
USER anki
VOLUME /data
EXPOSE 8000

# UN SOLO worker: la collezione Anki va aperta da un unico processo.
# Allo spegnimento: 30 s per le richieste in corso, poi l'app aspetta la sync e
# chiude la collezione (stop_grace_period in docker-compose.yml deve coprire tutto).
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--no-access-log", "--timeout-graceful-shutdown", "30"]
