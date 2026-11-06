# stick-frr: upstream FRRouting plus the bits the NetOps tool stack needs to talk to it:
#   - sshd with an `admin` user whose login shell is vtysh (clear-text CLI, like a real router)
#   - net-snmp (LibreNMS / Zabbix polling), lldpd (topology discovery), rsyslog (syslog export)
# FRR is GPL-2.0, so this image can be published.
ARG FRR_VERSION=10.7.1
FROM quay.io/frrouting/frr:${FRR_VERSION}

# hadolint ignore=DL3018
RUN apk add --no-cache bash net-snmp net-snmp-tools lldpd rsyslog openssh-server \
    && echo /usr/bin/vtysh >> /etc/shells \
    && mkdir -p /etc/stick /var/run/sshd

COPY snmpd.conf /etc/snmp/snmpd.conf
COPY rsyslog.conf /etc/rsyslog.conf
COPY --chmod=0755 stick-entrypoint.sh /usr/local/bin/stick-entrypoint

EXPOSE 22 161/udp

ENTRYPOINT ["/usr/local/bin/stick-entrypoint"]
