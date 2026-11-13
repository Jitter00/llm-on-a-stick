#!/bin/sh
# Start one MCP server on stdio: stick-mcp-entrypoint <netbox|aws|nautobot|librenms|zabbix|grafana|netmiko> [args...]
set -eu
server="${1:?usage: stick-mcp-entrypoint <server>}"
shift
case "$server" in
    netbox) exec /opt/mcp/netbox/bin/netbox-mcp "$@" ;;
    aws) exec /opt/mcp/aws/bin/awslabs.aws-api-mcp-server "$@" ;;
    nautobot) exec /opt/mcp/nautobot/bin/nautobot-mcp "$@" ;;
    librenms) exec /opt/mcp/librenms/bin/librenms-mcp "$@" ;;
    zabbix) exec /opt/mcp/zabbix/bin/zabbix-mcp "$@" ;;
    # Read-only: no tool that creates or changes anything in Grafana is registered.
    grafana) exec /opt/mcp/grafana/bin/mcp-grafana --disable-write "$@" ;;
    # Netmiko reads its devices and the commands it lets through from files: they come in as YAML text,
    # so that the lab's addresses stay in the repository (topologies/mcp.yaml) and out of the image.
    netmiko)
        printf '%s\n' "${STICK_NETMIKO_INVENTORY:?}" > /root/inventory.yml
        printf '%s\n' "${STICK_NETMIKO_COMMANDS:?}" > /root/commands.yml
        export NETMIKO_MCP_INVENTORY_FILE=/root/inventory.yml NETMIKO_MCP_COMMAND_FILE=/root/commands.yml
        exec /opt/mcp/netmiko/bin/netmiko-mcp "$@"
        ;;
    *) echo "unknown MCP server: $server" >&2; exit 64 ;;
esac
