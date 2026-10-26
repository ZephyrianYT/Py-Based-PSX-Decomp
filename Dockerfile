# PSX Reference Library: a reproducible container for the ref/ tools.
#
# The tools use only the Python standard library, so the image is just a slim
# Python runtime plus the ref/ folder. Nothing is installed with pip.
#
# Build:   docker build -t psx-ref .
# Use:     docker run --rm psx-ref                       # list commands
#          docker run --rm psx-ref test                  # run the self-tests
#          docker run --rm -v "$PWD/ref_out:/out" --user "$(id -u):$(id -g)" \
#                 psx-ref demo --out /out                # write images to ./ref_out
#
# Or use docker-compose.yml, which wraps these commands.

FROM python:3.12-slim

# Don't write .pyc files into the image, and flush output immediately so
# progress appears in `docker logs` / compose output as it happens.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Run as an unprivileged user. The tools only read ref/ and write to /out.
RUN useradd --create-home --uid 1000 psx \
    && mkdir /out \
    && chown psx:psx /out

# Copy only what the tools need (see .dockerignore for what is left out).
COPY --chown=psx:psx ref ./ref

USER psx

# Outputs (PNG, OBJ) go here; mount a host folder to keep them.
VOLUME ["/out"]

# `python -m ref <command>` is the single entry point (ref/__main__.py).
ENTRYPOINT ["python", "-m", "ref"]
CMD ["--help"]
