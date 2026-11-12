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

# --- AWS (the moto emulator) and Terraform ----------------------------------
# The host needs neither `aws` nor `terraform`: these run them in the toolbox image, as the model does.
# AWS_ENDPOINT_URL, the dummy credentials and the region come from `stick task start` (services/moto).
STICK_TOOLBOX_IMAGE="${STICK_TOOLBOX_IMAGE:-stick-toolbox:dev}"
# toolbox_run <directory under the workspace, or .> <command> [args]   (stdin is passed on)
# The workspace is /work there, as in a run; $STICK_CANARY_* are set too. For many commands, send one script:
#   toolbox_run . bash -euo pipefail -s <<'EOF' ... EOF
toolbox_run() {
    local dir=$1 var; shift
    local args=(--rm -i --network host --user "$(id -u):$(id -g)" -e HOME=/tmp
        -e AWS_ENDPOINT_URL -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION)
    for var in $(compgen -v STICK_CANARY_); do args+=(-e "$var"); done
    docker run "${args[@]}" -v "$STICK_WORKSPACE:/work" -w "/work/$dir" "$STICK_TOOLBOX_IMAGE" "$@"
}
# aws_cli ec2 describe-vpcs --query ...
aws_cli() { toolbox_run . aws "$@"; }
# tf <directory under the workspace> <terraform arguments>   e.g. tf net apply -auto-approve
tf() { local dir=$1; shift; toolbox_run "$dir" terraform "$@" </dev/null; }
# The start of every Terraform fixture: the provider takes its settings from the environment.
# shellcheck disable=SC2034  # used by the task scripts that source this file
TF_HEADER='terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

provider "aws" {}'

# --- LibreNMS --------------------------------------------------------------
# $STICK_LIBRENMS_URL comes from `stick task start`; the token is the service's default unless overridden.
LIBRENMS_TOKEN="${STICK_LIBRENMS_TOKEN:-0123456789abcdef0123456789abcdef}"
# librenms_api <METHOD> <path> [json]   e.g. librenms_api GET devices
# Prints the response body; fails (with the body on stderr) on an HTTP error.
librenms_api() {
    local method=$1 path=$2 body=${3:-} out
    local args=(-sS -X "$method" -H "X-Auth-Token: $LIBRENMS_TOKEN" -H "Accept: application/json")
    [[ -n "$body" ]] && args+=(-H "Content-Type: application/json" --data "$body")
    if ! out=$(curl "${args[@]}" -w '\n%{http_code}' "$STICK_LIBRENMS_URL/api/v0/${path#/}"); then
        echo "librenms_api $method $path: request failed" >&2; return 1
    fi
    local code=${out##*$'\n'}
    out=${out%$'\n'*}
    if [[ "$code" -ge 400 ]]; then
        echo "librenms_api $method $path: HTTP $code: $out" >&2; return 1
    fi
    printf '%s\n' "$out"
}
# Run `lnms <args>` in the LibreNMS container.
librenms_lnms() { docker exec stick-librenms-librenms-1 lnms "$@"; }
# librenms_poll <hostname|all>: discover and poll now, instead of waiting for the dispatcher. A device that
# doesn't answer makes lnms exit non-zero, which is fine here.
librenms_poll() {
    librenms_lnms device:discover "$1" -q >/dev/null 2>&1 || true
    librenms_lnms device:poll "$1" -q >/dev/null 2>&1 || true
}
# librenms_add_device <address> <community> [force]: add an SNMPv2c device, then discover and poll it.
# With "force", LibreNMS takes it without checking that it answers.
librenms_add_device() {
    local force=false
    [[ "${3:-}" == force ]] && force=true
    librenms_api POST devices "$(jq -n --arg h "$1" --arg c "$2" --argjson f "$force" \
        '{hostname: $h, version: "v2c", community: $c, force_add: $f}')" >/dev/null
    librenms_poll "$1"
}
# librenms_wait_snmp <address> <community> <text>: wait until the device's SNMP agent shows <text> in its
# system name or port descriptions. SR Linux takes a few seconds to publish a configuration change over
# SNMP (up to a minute for a port description); adding the device before that would store the old values.
librenms_wait_snmp() {
    local oid out
    for _ in $(seq 1 60); do
        for oid in SNMPv2-MIB::sysName IF-MIB::ifAlias; do
            # Into a variable, not a pipe: `grep -q` would close the pipe early and, with pipefail, fail.
            out=$(docker exec stick-librenms-librenms-1 snmpbulkwalk -v2c -c "$2" -t 2 -r 0 -OQv "$1" "$oid" \
                2>/dev/null || true)
            grep -qF -- "$3" <<<"$out" && return 0
        done
        sleep 1
    done
    echo "$1 does not show '$3' over SNMP (community $2)" >&2
    return 1
}
# librenms_add_devices <community> <address>...: the same for several devices, polled side by side.
librenms_add_devices() {
    local community=$1 ip pids=()
    shift
    for ip in "$@"; do
        librenms_api POST devices "$(jq -n --arg h "$ip" --arg c "$community" \
            '{hostname: $h, version: "v2c", community: $c}')" >/dev/null
    done
    for ip in "$@"; do librenms_poll "$ip" & pids+=($!); done
    wait "${pids[@]}"
}
# Set the SNMP community of an SR Linux node (containerlab's default entry). `stick task start` puts the
# boot value back: it is part of the configuration.
srl_snmp_community() {
    srl_set "$1" "set / system snmp access-group SNMPv2-RO-Community community-entry RO-Community community $2"
}

# --- Zabbix ----------------------------------------------------------------
# $STICK_ZABBIX_URL comes from `stick task start`; the token is the service's default unless overridden.
ZABBIX_TOKEN="${STICK_ZABBIX_TOKEN:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}"
ZABBIX_TEMPLATE="Network Generic Device by SNMP"
# zabbix_api <method> [params json]   e.g. zabbix_api host.get '{"output": ["host"]}'
# Prints the `result`; fails (with the error on stderr) when Zabbix answers with an error, which it does
# with HTTP 200.
zabbix_api() {
    local method=$1 params=${2:-"{}"} out
    if ! out=$(curl -sS -H "Authorization: Bearer $ZABBIX_TOKEN" -H "Content-Type: application/json" \
        --data "$(jq -n --arg m "$method" --argjson p "$params" '{jsonrpc: "2.0", method: $m, params: $p, id: 1}')" \
        "$STICK_ZABBIX_URL/api_jsonrpc.php"); then
        echo "zabbix_api $method: request failed" >&2; return 1
    fi
    if ! jq -e 'has("result")' <<<"$out" >/dev/null 2>&1; then
        echo "zabbix_api $method: $out" >&2; return 1
    fi
    jq -c .result <<<"$out"
}
# Have the server read new configuration (hosts, items, triggers) now instead of within a few seconds.
zabbix_reload() { docker exec stick-zabbix-server-1 zabbix_server -R config_cache_reload >/dev/null; sleep 1; }
# zabbix_group_id <name>: the host group's id; the group is created if it isn't there.
zabbix_group_id() {
    local id
    id=$(zabbix_api hostgroup.get "$(jq -n --arg n "$1" '{output: ["groupid"], filter: {name: [$n]}}')" \
        | jq -r '.[0].groupid // empty')
    [[ -n "$id" ]] || id=$(zabbix_api hostgroup.create "$(jq -n --arg n "$1" '{name: $n}')" | jq -r '.groupids[0]')
    printf '%s\n' "$id"
}
# zabbix_add_host <host name> <address> <community> [more host.create fields, as json]
# An SNMPv2c host the way Zabbix's own templates expect it: the community is the host macro
# {$SNMP_COMMUNITY} and the interface refers to it. In the group Routers, with the generic SNMP template,
# unless the extra fields say otherwise (e.g. '{"groups": [...], "tags": [...], "status": 1}').
zabbix_add_host() {
    local extra=${4:-"{}"} group template
    group=$(zabbix_group_id Routers)
    template=$(zabbix_api template.get "$(jq -n --arg n "$ZABBIX_TEMPLATE" '{output: ["templateid"], filter: {host: [$n]}}')" \
        | jq -er '.[0].templateid')
    zabbix_api host.create "$(jq -n --arg h "$1" --arg ip "$2" --arg c "$3" --arg g "$group" --arg t "$template" \
        --argjson extra "$extra" \
        '{host: $h, groups: [{groupid: $g}], templates: [{templateid: $t}],
          macros: [{macro: "{$SNMP_COMMUNITY}", value: $c}],
          interfaces: [{type: 2, main: 1, useip: 1, ip: $ip, dns: "", port: "161",
                        details: {version: 2, bulk: 1, community: "{$SNMP_COMMUNITY}"}}]} + $extra')" \
        | jq -r '.hostids[0]'
}
# zabbix_poll <host name> [key pattern]: poll the host's SNMP items (those whose key contains the pattern)
# now. "net.if.discovery" is the rule that finds the host's ports.
zabbix_poll() {
    local host ids id
    zabbix_reload
    host=$(zabbix_api host.get "$(jq -n --arg h "$1" '{output: ["hostid"], filter: {host: [$h]}}')" \
        | jq -er '.[0].hostid') || { echo "no Zabbix host $1" >&2; return 1; }
    ids=$( { zabbix_api item.get "$(jq -n --arg h "$host" --arg k "${2:-}" \
            '{hostids: [$h], output: ["itemid"], filter: {type: 20, status: 0}, search: {key_: $k}, limit: 40}')"
        zabbix_api discoveryrule.get "$(jq -n --arg h "$host" --arg k "${2:-}" \
            '{hostids: [$h], output: ["itemid"], search: {key_: $k}}')"; } | jq -r '.[].itemid')
    for id in $ids; do
        zabbix_api task.create "$(jq -n --arg i "$id" '[{type: 6, request: {itemid: $i}}]')" >/dev/null 2>&1 || true
    done
}
# zabbix_wait_available <host name> <1|2>: wait until Zabbix reaches the host over SNMP (1) or has given up
# on it (2), polling it meanwhile.
zabbix_wait_available() {
    local got
    for n in $(seq 1 45); do
        (( n % 3 == 1 )) && zabbix_poll "$1" system
        got=$(zabbix_api host.get "$(jq -n --arg h "$1" '{output: ["hostid"], filter: {host: [$h]},
            selectInterfaces: ["available"]}')" | jq -r '.[0].interfaces[0].available')
        [[ "$got" == "$2" ]] && return 0
        sleep 2
    done
    echo "Zabbix host $1: SNMP availability is $got, expected $2" >&2
    return 1
}
# zabbix_wait_items <host name> <text>: have Zabbix discover the host's ports now, and wait until it has an
# item whose name contains <text> (port items are named "Interface <ifName>(<description>): ...").
zabbix_wait_items() {
    local count
    for n in $(seq 1 45); do
        (( n % 10 == 1 )) && zabbix_poll "$1" net.if.discovery
        count=$(zabbix_api item.get "$(jq -n --arg h "$1" --arg t "$2" \
            '{host: $h, countOutput: true, search: {name: $t}}')" | jq -r .)
        [[ "$count" -gt 0 ]] && return 0
        sleep 2
    done
    echo "Zabbix host $1 has no item named like '$2'" >&2
    return 1
}
# snmp_wait <address> <community> <text>: wait until the device's SNMP agent shows <text> in its system name
# or port descriptions (see librenms_wait_snmp), asking from the toolbox image.
snmp_wait() {
    local oid out
    for _ in $(seq 1 60); do
        for oid in 1.3.6.1.2.1.1.5 1.3.6.1.2.1.31.1.1.1.18; do  # sysName, ifAlias (the image has no MIB files)
            out=$(docker run --rm --network host "$STICK_TOOLBOX_IMAGE" snmpbulkwalk -v2c -c "$2" -t 2 -r 0 -OQv \
                "$1" "$oid" 2>/dev/null || true)
            grep -qF -- "$3" <<<"$out" && return 0
        done
        sleep 1
    done
    echo "$1 does not show '$3' over SNMP (community $2)" >&2
    return 1
}

# --- Loki (the routers' syslog) -------------------------------------------
# Apply several SR Linux commands in one commit: srl_commit <container> "set / ..." "set / ..."
# (`sr_cli -ec`, which srl_set uses, takes one command.)
srl_commit() {
    local c=$1 out; shift
    if ! out=$(printf '%s\n' "enter candidate" "$@" "commit now" | docker exec -i "$c" sr_cli 2>&1) ||
        ! grep -q "All changes have been committed" <<<"$out"; then
        echo "srl_commit $c: $out" >&2; return 1
    fi
}
# An SSH login from a lab node (so the routers log that node's address), with a password and no terminal:
# ssh_login <from container> <target address> <user> <password>. Commands for the far end come on stdin.
# The exit status is ssh's: a refused password is not an error for a setup that wants failed logins.
ssh_login() {
    docker exec -i "$1" sh -c '
        printf "#!/bin/sh\necho %s\n" "$3" > /tmp/stick-askpass && chmod 700 /tmp/stick-askpass
        SSH_ASKPASS=/tmp/stick-askpass SSH_ASKPASS_REQUIRE=force DISPLAY=none setsid ssh -T \
            -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
            -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 -o ConnectTimeout=5 \
            "$2@$1" 2>/dev/null' sh "$2" "$3" "$4"
}
# How many log lines match a LogQL query in the last 15 minutes: loki_count '{host="frr1"} |= "x"'
loki_count() {
    curl -fsS -G "${STICK_LOKI_URL%/}/loki/api/v1/query" \
        --data-urlencode "query=sum(count_over_time($1 [15m]))" | jq -r '.data.result[0].value[1] // "0"'
}
# The matching lines, oldest first (at most 1000): loki_lines '{host="frr1"} |= "x"'
loki_lines() {
    curl -fsS -G "${STICK_LOKI_URL%/}/loki/api/v1/query_range" --data-urlencode "query=$1" \
        --data-urlencode "start=$(($(date +%s) - 900))" --data-urlencode limit=1000 \
        --data-urlencode direction=forward | jq -r '[.data.result[].values[]] | sort_by(.[0]) | .[][1]'
}
# Wait until Loki has exactly <count> lines for a query (syslog arrives a moment after the event):
# loki_wait '{host="frr1"} |= "x"' 3. More lines than that is an error: the setup would not be what the
# task's answer says.
loki_wait() {
    local query=$1 want=${2:-1} got=0
    for _ in $(seq 1 60); do
        got=$(loki_count "$query" 2>/dev/null || echo 0)
        [[ "$got" -eq "$want" ]] && return 0
        [[ "$got" -gt "$want" ]] && break
        sleep 1
    done
    echo "loki_wait: $got lines for $query, wanted $want" >&2
    return 1
}
