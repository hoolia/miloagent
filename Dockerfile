FROM python:3.13-slim

# Chromium + HOME write to group-writable paths so the image runs cleanly under
# both anyuid (root, on OpenShift) and an arbitrary non-root UID (GID 0).
ENV PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers \
    HOME=/app \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
# --with-deps pulls every system lib Chromium needs (the hand-curated apt list
# drifted and caused silent headless-launch failures).
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

# Runtime-writable dirs + OpenShift arbitrary-UID support (member of GID 0).
RUN mkdir -p data logs projects pw-browsers \
    && chgrp -R 0 /app \
    && chmod -R g=u /app

EXPOSE 8420

CMD ["python3", "miloagent.py", "run", "--web"]
