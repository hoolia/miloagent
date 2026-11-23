# MiloAgent bridge: read-only MCP server and /signals endpoint. Runs as any UID in group 0 (OpenShift restricted-v2 SCC).
FROM registry.access.redhat.com/ubi9/python-312-minimal:9.9-1794502907@sha256:612eb994cd4255fbafd0de6967efba8d72b62c812058e68e28974458529d0523 AS build

USER 0
WORKDIR /build
# dependencies from the hashed lock file (uv pip compile), then the package without deps
COPY requirements.lock ./
RUN python3 -m venv /opt/miloagent-bridge \
 && /opt/miloagent-bridge/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes -r requirements.lock \
 && /opt/miloagent-bridge/bin/pip uninstall -y pip

FROM registry.access.redhat.com/ubi9/python-312-minimal:9.9-1794502907@sha256:612eb994cd4255fbafd0de6967efba8d72b62c812058e68e28974458529d0523

LABEL org.opencontainers.image.title="miloagent-bridge" \
      org.opencontainers.image.description="Read-only MCP server and HTTP signals endpoint over MiloAgent findings. No write path to MiloAgent." \
      org.opencontainers.image.source="https://github.com/hoolia/miloagent" \
      org.opencontainers.image.licenses="MIT"

COPY --from=build /opt/miloagent-bridge /opt/miloagent-bridge
COPY src/miloagent_bridge /opt/miloagent-bridge/app/miloagent_bridge
ENV PATH=/opt/miloagent-bridge/bin:$PATH \
    PYTHONPATH=/opt/miloagent-bridge/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp

# arbitrary UID, root group, nothing writable needed
USER 1001
EXPOSE 8000
ENTRYPOINT ["python3", "-m", "miloagent_bridge.server"]
