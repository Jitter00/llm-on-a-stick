# stick-mcp: the upstream MCP servers a model works through, one virtualenv each (their
# dependency pins conflict). `stick run` starts one container per server and attempt and talks to it over
# stdio: `docker run -i --network host stick-mcp:dev <server>`. On the host network a server reaches the
# services' host ports exactly like the toolbox does.
FROM python:3.13-slim-bookworm

# Each server comes from a hash-pinned list: requirements/<server>.in names the server and its version,
# requirements/<server>.txt is `uv pip compile --generate-hashes --universal --python-version 3.13` of it.
COPY requirements /tmp/requirements
RUN for server in netbox aws nautobot librenms zabbix grafana netmiko powerdns; do \
        python -m venv "/opt/mcp/$server" \
        && "/opt/mcp/$server/bin/pip" install --no-cache-dir --require-hashes -r "/tmp/requirements/$server.txt" \
        || exit 1; \
    done \
    && rm -rf /tmp/requirements

# gitea-mcp is a Go program: its release archive, checked against the checksum of that release
# (gitea-mcp_<version>_checksums.txt), for the architecture the image is built for.
RUN python - <<'PY'
import hashlib, io, platform, tarfile, urllib.request

VERSION = "1.13.0"
ARCHIVES = {
    "x86_64": ("x86_64", "23383ad6adbb7a8a6a848ac736c07de19417d26311c3581160b356db01b3366d"),
    "aarch64": ("arm64", "b12335dbf1590e3f306a376789de192d37e9ae7729c28272081764d0dca87b07"),
}
arch, digest = ARCHIVES[platform.machine()]
url = f"https://gitea.com/gitea/gitea-mcp/releases/download/v{VERSION}/gitea-mcp_Linux_{arch}.tar.gz"
data = urllib.request.urlopen(url, timeout=120).read()
assert hashlib.sha256(data).hexdigest() == digest, f"checksum mismatch for {url}"
with tarfile.open(fileobj=io.BytesIO(data)) as archive:
    archive.extract("gitea-mcp", "/opt/mcp/gitea", filter="data")
PY

# PowerDNS has no MCP server of its own: awslabs.openapi-mcp-server makes one from PowerDNS's OpenAPI
# description. This file is an unchanged copy of what the pinned PowerDNS serves at /api/docs (which needs the
# API key, so the server can't fetch it itself); tests/integration/test_powerdns.py compares the two.
COPY powerdns-api.yaml /opt/mcp/powerdns-api/powerdns-api.yaml

COPY stick-mcp-entrypoint.sh /usr/local/bin/stick-mcp-entrypoint

# Raise together with MCP_IMAGE_VERSION in src/llm_on_a_stick/runner/mcp.py when a server or its version
# changes: `stick run` rebuilds an older stick-mcp:dev instead of running tasks against other tools.
LABEL stick.mcp.version="5"

ENV PYTHONUNBUFFERED=1
WORKDIR /root
ENTRYPOINT ["stick-mcp-entrypoint"]
