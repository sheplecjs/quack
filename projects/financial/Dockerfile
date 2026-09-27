FROM ghcr.io/astral-sh/uv:0.12.19-python3.14-trixie@sha256:c3534062316f77847b8d6b9aff1ffd2886c7838c3bea71a2f19051c778c2c383

ENV UV_NO_DEV=1

ARG UID=1001
ARG GID=1001
RUN groupadd -g ${GID} nonroot && useradd -r -m -u ${UID} -g ${GID} nonroot
USER nonroot

WORKDIR /app

COPY --from=workspace --chown=nonroot pyproject.toml uv.lock /app/
COPY --from=workspace --chown=nonroot projects/financial/pyproject.toml /app/projects/financial/

RUN uv sync --frozen --package financial --group dbt --no-install-workspace

COPY --chown=nonroot profiles.yml /app/
COPY --chown=nonroot financial_dbt/ /app/

RUN uv run --no-sync dbt deps

ENV PATH=/app/.venv/bin:$PATH \
    DUCKDB_PATH=../data/data.duckdb \
    DBT_TARGET_PATH=/data/target \
    DBT_LOG_PATH=/data/logs

VOLUME /data

ENTRYPOINT [ "bash", "build_and_render.sh" ]
