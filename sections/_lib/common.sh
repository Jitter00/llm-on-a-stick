#!/bin/bash
# Helpers for task setup and oracle scripts. Source with:  source "$STICK_LIB/common.sh"
# Containers are passed as $STICK_NODE_<NAME> (e.g. $STICK_NODE_SRL1), management IPs as $STICK_NODE_<NAME>_IP.

SRL_PASSWORD="${STICK_SRL_PASSWORD:-NokiaSrl1!}"

# --- SR Linux --------------------------------------------------------------
# Apply and commit one or more `set` commands (candidate mode, commit at the end).
srl_set() { local c=$1; shift; docker exec "$c" sr_cli -ec "$@" >/dev/null; }
# Run a CLI command and print its output (what an SSH user sees).
srl_cli() { docker exec "$1" sr_cli -d "$2"; }

# --- FRR -------------------------------------------------------------------
# Configure: frr_conf <container> "interface eth3" "description x" ...
frr_conf() {
    local c=$1; shift
    local args=(-c "conf t")
    for line in "$@"; do args+=(-c "$line"); done
    docker exec "$c" vtysh "${args[@]}" >/dev/null
}
# Run a command as the `admin` user, exactly what an SSH session returns.
frr_cli() { docker exec "$1" su -s /bin/sh admin -c "vtysh -c \"$2\""; }

# --- NETCONF ---------------------------------------------------------------
# netconf_get_config <ip> [filter-xml-file]  -> prints the <rpc-reply> to <get-config> on running.
# Uses the base:1.0 end-of-message framing; needs `ssh` and `sshpass` on the host.
netconf_get_config() {
    local ip=$1 filter_file=${2:-} filter=""
    [[ -n "$filter_file" ]] && filter="<filter type=\"subtree\">$(cat "$filter_file")</filter>"
    {
        printf '%s\n]]>]]>\n' '<?xml version="1.0" encoding="UTF-8"?><hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0"><capabilities><capability>urn:ietf:params:netconf:base:1.0</capability></capabilities></hello>'
        printf '%s\n]]>]]>\n' "<?xml version=\"1.0\" encoding=\"UTF-8\"?><rpc message-id=\"1\" xmlns=\"urn:ietf:params:xml:ns:netconf:base:1.0\"><get-config><source><running/></source>${filter}</get-config></rpc>"
        printf '%s\n]]>]]>\n' '<?xml version="1.0" encoding="UTF-8"?><rpc message-id="2" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0"><close-session/></rpc>'
        sleep 5
    } | sshpass -p "$SRL_PASSWORD" ssh -o LogLevel=ERROR -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -p 830 "admin@$ip" -s netconf \
      | python3 -c 'import sys; parts = sys.stdin.read().split("]]>]]>"); print(next(p.strip() for p in parts if "message-id=\"1\"" in p))'
}

# --- Oxidized --------------------------------------------------------------
OXIDIZED_URL="http://127.0.0.1:${STICK_OXIDIZED_PORT:-8888}"
# Time (epoch seconds) when Oxidized last finished backing up a node successfully, or 0.
oxidized_last_success() {
    curl -sf "$OXIDIZED_URL/nodes.json" | python3 -c '
import json, sys, datetime
node = sys.argv[1]
for n in json.load(sys.stdin):
    last = n.get("last") or {}
    if n["name"] == node and last.get("status") == "success":
        end = last["end"].replace(" UTC", "+00:00")
        print(int(datetime.datetime.fromisoformat(end).timestamp())); break
else:
    print(0)' "$1"
}
# Back up a node now and wait until that backup has finished. (Oxidized only stores a new version
# when the config changed, so we wait for the run itself, not for a new version.)
oxidized_backup_now() {
    local node=$1 started
    started=$(date +%s)
    curl -sf -o /dev/null "$OXIDIZED_URL/node/next/$node"
    for _ in $(seq 1 30); do
        [[ "$(oxidized_last_success "$node")" -ge "$started" ]] && return 0
        sleep 2
    done
    echo "Oxidized did not back up $node within 60 s" >&2
    return 1
}

# --- NetBox ----------------------------------------------------------------
# $STICK_NETBOX_URL (host URL) and $STICK_NETBOX_AUTH (the Authorization header) come from `stick task start`.
# netbox_api <METHOD> <path> [json]   e.g. netbox_api POST dcim/devices/ '{"name": "x", ...}'
# Prints the response body; fails (with the body on stderr) on an HTTP error.
netbox_api() {
    local method=$1 path=$2 body=${3:-} out
    local args=(-sS -X "$method" -H "Authorization: $STICK_NETBOX_AUTH" -H "Accept: application/json")
    [[ -n "$body" ]] && args+=(-H "Content-Type: application/json" --data "$body")
    if ! out=$(curl "${args[@]}" -w '\n%{http_code}' "$STICK_NETBOX_URL/api/${path#/}"); then
        echo "netbox_api $method $path: request failed" >&2; return 1
    fi
    local code=${out##*$'\n'}
    out=${out%$'\n'*}
    if [[ "$code" -ge 400 ]]; then
        echo "netbox_api $method $path: HTTP $code: $out" >&2; return 1
    fi
    printf '%s\n' "$out"
}
# netbox_id <path with filters>  -> id of the first match, e.g. netbox_id "dcim/devices/?name=srl2"
netbox_id() { netbox_api GET "$1" | jq -er '.results[0].id'; }

# --- Nautobot --------------------------------------------------------------
# $STICK_NAUTOBOT_URL and $STICK_NAUTOBOT_AUTH ("Token <hex>") come from `stick task start`.
# nautobot_api <METHOD> <path> [json]   e.g. nautobot_api POST dcim/devices/ '{"name": "x", ...}'
# Prints the response body; fails (with the body on stderr) on an HTTP error.
nautobot_api() {
    local method=$1 path=$2 body=${3:-} out
    local args=(-sS -X "$method" -H "Authorization: $STICK_NAUTOBOT_AUTH" -H "Accept: application/json")
    [[ -n "$body" ]] && args+=(-H "Content-Type: application/json" --data "$body")
    if ! out=$(curl "${args[@]}" -w '\n%{http_code}' "$STICK_NAUTOBOT_URL/api/${path#/}"); then
        echo "nautobot_api $method $path: request failed" >&2; return 1
    fi
    local code=${out##*$'\n'}
    out=${out%$'\n'*}
    if [[ "$code" -ge 400 ]]; then
        echo "nautobot_api $method $path: HTTP $code: $out" >&2; return 1
    fi
    printf '%s\n' "$out"
}
# nautobot_id <path with filters>  -> UUID of the first match, e.g. nautobot_id "dcim/devices/?name=srl2"
nautobot_id() { nautobot_api GET "$1" | jq -er '.results[0].id'; }
