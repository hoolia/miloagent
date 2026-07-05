FROM python:3.13-slim

ENV HOME=/app \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime-writable dirs + OpenShift arbitrary-UID support (member of GID 0).
RUN mkdir -p data logs projects \
    && chgrp -R 0 /app \
    && chmod -R g=u /app

EXPOSE 8420

CMD ["python3", "miloagent.py", "run", "--web"]
