#!/bin/sh
# Start one MCP server on stdio: stick-mcp-entrypoint <netbox|aws|nautobot|librenms|zabbix|grafana> [args...]
set -eu
server="${1:?usage: stick-mcp-entrypoint <server>}"
shift
case "$server" in
    netbox) exec /opt/mcp/netbox/bin/netbox-mcp-server "$@" ;;
    aws) exec /opt/mcp/aws/bin/awslabs.aws-api-mcp-server "$@" ;;
    nautobot) exec /opt/mcp/nautobot/bin/nautobot-mcp "$@" ;;
    librenms) exec /opt/mcp/librenms/bin/librenms-mcp "$@" ;;
    zabbix) exec /opt/mcp/zabbix/bin/zabbix-mcp "$@" ;;
    # Read-only: no tool that creates or changes anything in Grafana is registered.
    grafana) exec /opt/mcp/grafana/bin/mcp-grafana --disable-write "$@" ;;
    *) echo "unknown MCP server: $server" >&2; exit 64 ;;
esac
