#!/bin/bash
# Start the side services, seed FRR config from read-only mounts, then hand over to FRR.
set -euo pipefail

ADMIN_USER="${STICK_ADMIN_USER:-admin}"
ADMIN_PASSWORD="${STICK_ADMIN_PASSWORD:-admin}"
SNMP_COMMUNITY="${STICK_SNMP_COMMUNITY:-stick-ro}"

# Config is mounted read-only under /etc/stick so `write memory` never touches the repo.
for f in frr.conf daemons; do
    if [[ -f "/etc/stick/$f" ]]; then
        cp "/etc/stick/$f" "/etc/frr/$f"
    fi
done
# Without vtysh.conf, every vtysh session of a non-root user starts with two warning lines
# ("Can't open configuration file /etc/frr/vtysh.conf" ...), which pollute CLI output and backups.
if [[ ! -f /etc/frr/vtysh.conf ]]; then
    echo "service integrated-vtysh-config" > /etc/frr/vtysh.conf
fi
chown -R frr:frr /etc/frr

# CLI user: SSH lands straight in vtysh, like logging into a router.
if ! id "$ADMIN_USER" >/dev/null 2>&1; then
    adduser -D -s /usr/bin/vtysh "$ADMIN_USER"
    for g in frrvty frr; do
        if getent group "$g" >/dev/null; then addgroup "$ADMIN_USER" "$g"; fi
    done
fi
echo "${ADMIN_USER}:${ADMIN_PASSWORD}" | chpasswd

ssh-keygen -A >/dev/null
# Lab-only settings: password login for the CLI user, no root login.
/usr/sbin/sshd -o PasswordAuthentication=yes -o PermitRootLogin=no

sed -i "s/^rocommunity .*/rocommunity ${SNMP_COMMUNITY} default/" /etc/snmp/snmpd.conf
# -C: don't also read the default config path, or snmpd.conf is loaded twice and udp:161 binds twice.
snmpd -Lsd -C -c /etc/snmp/snmpd.conf

mkdir -p /etc/rsyslog.d
if [[ -n "${STICK_SYSLOG_TARGET:-}" ]]; then
    echo "*.* @@${STICK_SYSLOG_TARGET}" > /etc/rsyslog.d/stick-forward.conf
fi
rsyslogd

lldpd

exec /usr/lib/frr/docker-start
