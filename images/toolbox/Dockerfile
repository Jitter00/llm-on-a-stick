# stick-toolbox: where a model's commands run during `stick run`.
# It joins the host network, so it reaches the lab's management addresses and the services' host ports
# exactly like an engineer on the host would. The run's workspace is mounted at the same path as on the host.
FROM python:3.13-slim-bookworm

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client sshpass curl jq iputils-ping netcat-openbsd \
       dnsutils procps less \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir ncclient==0.7.1 netconf-console2==3.0.1 pyyaml==6.0.3

# Lab devices are recreated often: don't stop on changed host keys (an environment detail, not a skill).
COPY ssh_config /etc/ssh/ssh_config.d/stick.conf

ENV PAGER=cat TERM=dumb
WORKDIR /root
CMD ["sleep", "infinity"]
