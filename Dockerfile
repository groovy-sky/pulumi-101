# Stage 1: Build the Pulumi Go program
# Stage 1: collect IaC assets only
FROM alpine:3.19 AS assets
WORKDIR /src
COPY env/ ./env/
COPY services/ ./services/
COPY azure-infra/ ./azure-infra/
RUN find . -type f >/dev/null

# Stage 2: runnable Pulumi CLI image
FROM pulumi/pulumi:latest
WORKDIR /workspace
COPY --from=assets /src/ ./
COPY README.md ./README.md
ENTRYPOINT ["pulumi"]
