# stick-toolbox: where a model's commands run during `stick run`.
# It joins the host network, so it reaches the lab's management addresses and the services' host ports
# exactly like an engineer on the host would. The run's workspace is mounted at the same path as on the host.
FROM python:3.13-slim-bookworm

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client sshpass curl jq iputils-ping netcat-openbsd \
       dnsutils procps less snmp \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir ncclient==0.7.1 netconf-console2==3.0.1 pyyaml==6.0.3 boto3==1.43.126

# Cloud tools (the aws and terraform sections): AWS CLI v2, Terraform, and Terraform's AWS provider unpacked
# where Terraform looks for local copies, so `terraform init` installs it in a second without the registry.
ARG TARGETARCH
ARG AWSCLI_VERSION=2.39.6
ARG TERRAFORM_VERSION=1.17.1
ARG TERRAFORM_AWS_VERSION=6.72.0
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends unzip \
    && rm -rf /var/lib/apt/lists/* \
    && arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "$arch" in amd64) awsarch=x86_64 ;; arm64) awsarch=aarch64 ;; *) echo "unsupported $arch"; exit 1 ;; esac \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${awsarch}-${AWSCLI_VERSION}.zip" -o /tmp/aws.zip \
    && unzip -q /tmp/aws.zip -d /tmp && /tmp/aws/install && rm -rf /tmp/aws /tmp/aws.zip \
    && curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${arch}.zip" -o /tmp/tf.zip \
    && unzip -q /tmp/tf.zip terraform -d /usr/local/bin && rm /tmp/tf.zip \
    && dir="/usr/share/terraform/plugins/registry.terraform.io/hashicorp/aws/${TERRAFORM_AWS_VERSION}/linux_${arch}" \
    && mkdir -p "$dir" \
    && curl -fsSL "https://releases.hashicorp.com/terraform-provider-aws/${TERRAFORM_AWS_VERSION}/terraform-provider-aws_${TERRAFORM_AWS_VERSION}_linux_${arch}.zip" -o /tmp/p.zip \
    && unzip -q /tmp/p.zip -d "$dir" && rm /tmp/p.zip

# The grader's reader of the emulated AWS account (the aws_unchanged check).
COPY aws_snapshot.py /usr/local/lib/stick/aws_snapshot.py

# Lab devices are recreated often: don't stop on changed host keys (an environment detail, not a skill).
COPY ssh_config /etc/ssh/ssh_config.d/stick.conf

# Raise together with TOOLBOX_VERSION in src/llm_on_a_stick/runner/toolbox.py when the image's tools change:
# `stick run` rebuilds an older stick-toolbox:dev instead of running tasks without the new tools.
LABEL stick.toolbox.version="3"

ENV PAGER=cat TERM=dumb AWS_PAGER= CHECKPOINT_DISABLE=1 TF_IN_AUTOMATION=1
WORKDIR /root
CMD ["sleep", "infinity"]
