FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY pipeline ./pipeline
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["pipeline"]
CMD ["--help"]
