FROM python:3.13-slim AS dependencies
WORKDIR /app
RUN pip install --no-cache-dir uv==0.8.22
COPY pyproject.toml uv.lock LICENSE NOTICE ./
COPY src/ src/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev --extra pg --no-editable

FROM python:3.13-slim
WORKDIR /app
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin atlas \
    && mkdir /data && chown atlas:atlas /data
COPY --from=dependencies /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    ATLAS_DATA_DIR=/data PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "atlas_graph.hosted:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
