FROM docker.io/library/python:3.13-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

WORKDIR /build
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache

FROM docker.io/library/python:3.13-slim

ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY manage.py ./
COPY config/ config/
COPY main/ main/

RUN DJANGO_ENV=development python manage.py collectstatic --noinput \
    && mkdir /data \
    && ln -s /data/db.sqlite3 /app/db.sqlite3 \
    && chown 10001:10001 /app /data

USER 10001:10001
EXPOSE 8000
CMD ["/bin/sh", "-c", "python manage.py migrate --noinput && exec gunicorn --bind 0.0.0.0:8000 config.wsgi:application"]
