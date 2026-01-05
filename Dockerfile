FROM docker.io/python:3.11-slim AS runtime

ARG PULUMI_VERSION=3.117.0
ENV PULUMI_HOME=/opt/pulumi \
	PATH="/opt/pulumi:${PATH}"

RUN apt-get update \
	&& apt-get install -y --no-install-recommends curl ca-certificates \
	&& rm -rf /var/lib/apt/lists/*

RUN mkdir -p "$PULUMI_HOME" \
	&& curl -fsSL "https://get.pulumi.com/releases/sdk/pulumi-v${PULUMI_VERSION}-linux-x64.tar.gz" \
	| tar -xz -C "$PULUMI_HOME" --strip-components=1

RUN pip install --no-cache-dir --upgrade pip \
	&& pip install --no-cache-dir \
		"pulumi>=3.100.0,<4.0.0" \
		pulumi-azure-native \
		pulumi-random \
		pulumi-tls \
		pulumi-command

WORKDIR /workspace

COPY roles/ ./roles/
COPY services/ ./services/
COPY shared/ ./shared/
COPY catalog.yaml pulumiw.py README.md ./

ENTRYPOINT ["pulumi"]
