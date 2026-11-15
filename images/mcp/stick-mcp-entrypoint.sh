#!/bin/sh
# Start one MCP server on stdio: stick-mcp-entrypoint <netbox|aws|nautobot|librenms|zabbix|grafana|netmiko|gitea|powerdns> [args...]
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
    gitea) exec /opt/mcp/gitea/gitea-mcp "$@" ;;
    # A generic OpenAPI server pointed at PowerDNS's API. --no-validate-output: PowerDNS's search answers
    # don't match its own description, and the server would turn them into errors.
    powerdns)
        exec /opt/mcp/powerdns/bin/awslabs.openapi-mcp-server --api-name powerdns \
            --api-url "${POWERDNS_API_URL:?}" --auth-type api_key --auth-api-key "${POWERDNS_API_KEY:?}" \
            --auth-api-key-name X-API-Key --auth-api-key-in header \
            --allow-insecure-http --allow-private-networks --no-validate-output \
            --spec-path /opt/mcp/powerdns-api/powerdns-api.yaml --allowed-spec-dirs /opt/mcp/powerdns-api "$@"
        ;;
    *) echo "unknown MCP server: $server" >&2; exit 64 ;;
esac
