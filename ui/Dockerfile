# PSX Decomp Studio web UI. Build from the repository root:
#
#   docker build -f ui/Dockerfile -t psx-ui .
#   docker run --rm -p 8501:8501 psx-ui            # then open http://localhost:8501
#   docker run --rm -p 8501:8501 -e PSX_UI_PASSWORD=secret psx-ui   # with a password
#
# Or: docker compose up ui

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UI_PORT=8501 \
    UI_BIND=0.0.0.0

WORKDIR /app

RUN useradd --create-home --uid 1000 psx

# Dependencies first, so code changes do not reinstall Streamlit.
COPY ui/requirements.txt ui/requirements.txt
RUN pip install --no-cache-dir -r ui/requirements.txt

COPY --chown=psx:psx ref ./ref
COPY --chown=psx:psx ui ./ui

USER psx
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/_stcore/health' % os.environ.get('UI_PORT','8501'))" || exit 1

ENTRYPOINT ["/app/ui/entrypoint.sh"]
