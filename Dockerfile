# Stage 1: Build the Pulumi Go program
# Stage 1: collect IaC assets only
FROM docker.io/alpine:3.19 AS assets
WORKDIR /src
COPY env/ ./env/
COPY azure/ ./azure/

# Stage 2: runnable Pulumi CLI image
FROM docker.io/pulumi/pulumi:latest
WORKDIR /workspace
COPY --from=assets /src/ ./
COPY README.md ./README.md
ENTRYPOINT ["pulumi"]
