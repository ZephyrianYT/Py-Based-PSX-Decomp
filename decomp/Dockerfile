# PSX Decomp Studio: Binary Analysis stage (Ghidra headless + PS1 scripts).
#
# Base: blacktop/ghidra, a maintained image of the official NSA Ghidra release
# (Ghidra 12.1.4 + JDK 21 at /ghidra). Pinned to a version this repository's
# integration test has run against.
#
# Build (from the repository root):
#   docker build -f decomp/Dockerfile -t psx-decomp .
# Use:
#   docker run --rm -v "$PWD/work:/work" psx-decomp analyze /work/GAME.EXE --out /work/out
#   docker compose run --rm decomp analyze /work/GAME.EXE --out /work/out

FROM blacktop/ghidra:12.1.4

ENV GHIDRA_INSTALL_DIR=/ghidra \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && (getent passwd 1000 >/dev/null || useradd --create-home --uid 1000 psx) \
    && mkdir /work && chown 1000:1000 /work

WORKDIR /app
COPY --chown=1000:1000 ref ./ref
COPY --chown=1000:1000 decomp ./decomp

# uid 1000: an unprivileged user (Ubuntu images name it 'ubuntu')
USER 1000
VOLUME ["/work"]

# The base image's /entrypoint.sh launches the Ghidra GUI; replace it.
ENTRYPOINT ["python3", "-m", "decomp"]
CMD ["--help"]
