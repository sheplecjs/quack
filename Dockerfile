FROM ghcr.io/astral-sh/uv:0.13.5-python3.14-trixie@sha256:00c6beb41f4ceb136a7e28a48f9d7ded75f85f4e99bce30a6c89dffbd5d10d7c

ARG PROJECT
RUN test -n "$PROJECT" || (echo "PROJECT build arg is required" >&2 && exit 1)

ENV UV_NO_DEV=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

ARG UID=1001
ARG GID=1001
RUN groupadd -g ${GID} nonroot && useradd -r -m -u ${UID} -g ${GID} nonroot \
    && mkdir /data && chown nonroot:nonroot /data
USER nonroot

WORKDIR /app

COPY --chown=nonroot pyproject.toml uv.lock /app/
COPY --chown=nonroot projects/${PROJECT}/pyproject.toml /app/projects/${PROJECT}/
COPY --chown=nonroot packages/runtime/pyproject.toml /app/packages/runtime/
RUN uv sync --frozen --package ${PROJECT} --group dbt --group deploy --no-install-workspace

COPY --chown=nonroot projects/${PROJECT}/README.md /app/projects/${PROJECT}/
COPY --chown=nonroot projects/${PROJECT}/src /app/projects/${PROJECT}/src
COPY --chown=nonroot packages/runtime/src /app/packages/runtime/src
RUN uv sync --frozen --package ${PROJECT} --group dbt --group deploy --no-editable

COPY --chown=nonroot projects/${PROJECT}/profiles.yml /app/
COPY --chown=nonroot projects/${PROJECT}/.dlt/config.toml /app/.dlt/config.toml
COPY --chown=nonroot projects/${PROJECT}/${PROJECT}_dbt/ /app/

RUN /app/.venv/bin/dbt deps

ENV PATH=/app/.venv/bin:$PATH \
    QUACK_PROJECT=${PROJECT} \
    DUCKDB_PATH=../data/data.duckdb \
    DBT_TARGET_PATH=/data/target \
    DBT_LOG_PATH=/data/logs

VOLUME /data

CMD [ "bash", "-c", "dbt build && dbt docs generate --static && mkdir -p /data/report && cp /data/target/static_index.html /data/report/dbt_docs.html && bash render_reports.sh /data/report" ]
