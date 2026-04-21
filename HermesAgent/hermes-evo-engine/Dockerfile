# ── Stage 1: Builder ───────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . 2>/dev/null || true

COPY src/ src/
RUN pip install --no-cache-dir .

# ── Stage 2: Runtime ──────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# 从 builder 复制已安装的包
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /app/src /app/src

# 创建非 root 用户
RUN groupadd -r hermes && useradd -r -g hermes hermes \
    && mkdir -p /app/skill_store && chown -R hermes:hermes /app
USER hermes

# 环境变量
ENV PYTHONPATH=/app/src \
    HERMES_SKILL_STORE_PATH=/app/skill_store \
    HERMES_LOG_LEVEL=INFO

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:8000/health'); r.raise_for_status()"

CMD ["uvicorn", "hermes_evo.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
