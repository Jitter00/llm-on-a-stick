# stick-mcp: the upstream MCP servers a model works through in the mcp section, one virtualenv each (their
# dependency pins conflict). `stick run` starts one container per server and attempt and talks to it over
# stdio: `docker run -i --network host stick-mcp:dev <server>`. On the host network a server reaches the
# services' host ports exactly like the toolbox does.
FROM python:3.13-slim-bookworm

# Each server comes from a hash-pinned list: requirements/<server>.in names the server and its version,
# requirements/<server>.txt is `uv pip compile --generate-hashes --universal --python-version 3.13` of it.
COPY requirements /tmp/requirements
RUN for server in netbox aws nautobot librenms zabbix grafana; do \
        python -m venv "/opt/mcp/$server" \
        && "/opt/mcp/$server/bin/pip" install --no-cache-dir --require-hashes -r "/tmp/requirements/$server.txt" \
        || exit 1; \
    done \
    && rm -rf /tmp/requirements

COPY stick-mcp-entrypoint.sh /usr/local/bin/stick-mcp-entrypoint

# Raise together with MCP_IMAGE_VERSION in src/llm_on_a_stick/runner/mcp.py when a server or its version
# changes: `stick run` rebuilds an older stick-mcp:dev instead of running tasks against other tools.
LABEL stick.mcp.version="2"

ENV PYTHONUNBUFFERED=1
WORKDIR /root
ENTRYPOINT ["stick-mcp-entrypoint"]
