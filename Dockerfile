FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY --chown=0:0 requirements.txt .
COPY --chown=0:0 deploy/prepare_image.py /tmp/prepare_image.py
RUN python /tmp/prepare_image.py /app
RUN pip install -r requirements.txt && useradd --uid 10001 --no-create-home qsv
COPY --chown=0:0 src ./src
# QNAP ACLs can deny named users even when ordinary mode bits are 0644.
# Normalize only image-owned files, including /app and directory defaults.
RUN python /tmp/prepare_image.py /app
USER 10001:10001
# Fail at build time if runtime imports or static assets are unreadable.
RUN python -c "import src.api; from pathlib import Path; [p.read_bytes() for p in Path('src').rglob('*') if p.is_file()]"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log"]
