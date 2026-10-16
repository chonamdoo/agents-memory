FROM ghcr.io/astral-sh/uv:0.13.1 AS uv

FROM postgres:18.6-trixie AS python-base
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        python3=3.13.5-1 \
        python3-venv=3.13.5-1 \
        age=1.2.1-1+b5 \
    && rm -rf /var/lib/apt/lists/*

FROM python-base AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/agents-memory/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy
WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/agents_memory ./src/agents_memory
RUN uv sync --frozen --no-dev --no-editable --no-cache --python /usr/bin/python3

FROM python-base AS runtime
ARG APP_UID
ARG APP_GID
RUN case "$APP_UID" in ''|*[!0-9]*) exit 1;; esac \
    && case "$APP_GID" in ''|*[!0-9]*) exit 1;; esac \
    && test "$APP_UID" -gt 0 \
    && test "$APP_GID" -gt 0 \
    && install -d -m 0755 /opt/agents-memory
COPY --from=build /opt/agents-memory/venv /opt/agents-memory/venv
ENV PATH=/opt/agents-memory/venv/bin:/usr/lib/postgresql/18/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp
WORKDIR /opt/agents-memory
USER ${APP_UID}:${APP_GID}
STOPSIGNAL SIGTERM
ENTRYPOINT ["/opt/agents-memory/venv/bin/agents-memory"]
CMD ["serve"]
