# Copilot Instructions

## Repo Fundamentals
- YAML-first catalog: `env/` exposes ARM-managed values, `services/` hosts independent Pulumi projects, and `azure-infra/` stores reusable ARM/Bicep templates.
- Each project keeps its own `Pulumi.<stack>.yaml`; environment drift lives there, never inside `Pulumi.yaml`.
- `azure-infra/containerGroup.json` is the deployed template, with `containerGroup.bicep` maintained manually for readability.

## Architecture Overview
- `env`: contract-only stack (no resources) that surfaces subscription, RG, subnet, Key Vault, and Log Analytics IDs/URIs from literal config keys (`arm:*`).
- `services/container-group`: references `env` (`envStackRef`), feeds `azure-native:resources:Deployment` with `azure-infra/containerGroup.json`, and outputs container IDs/FQDN.
- `services/ops`: references both `env` and the container-group stack to re-share human-friendly IDs for operators; extend here for diagnostics/alerts.

## Config & Stack References
- Every service config starts by pointing to `env` (e.g., `envStackRef: your-org/env/dev`). Additional dependencies get their own stack reference keys (`containerGroupStackRef`, etc.).
- `env/Pulumi.<env>.yaml` files are the single source of truth for ARM-provided identifiers; mirror exact ARM values and avoid recomputing them elsewhere.
- Service configs drive runtime knobs (`name`, `image`, `port`, `cpuCores`, `memoryInGb`, `restartPolicy`, `zone`, `tags`). Keep YAML generic and change behavior through config.
- Use `pulumi config set --secret` for sensitive data so stack files remain encrypted.

## Resource Patterns
- Use `variables:` for derived strings (`subnetId`, `logAnalyticsWorkspaceId`, `keyVaultUri`) instead of repeating interpolation.
- When replaying ARM/Bicep, load JSON with `fn::file` + `fn::fromJSON`, then pass `properties.parameters.<param>.value` exactly as shown in `services/container-group/Pulumi.yaml`.
- Outputs should stay human-friendly (names, IDs, URLs) so downstream services like `ops` can forward them without transformations.

## Workflows & Commands
- Local flow: `pulumi -C env up`, then `pulumi -C services/container-group up`, then any additional service (`pulumi -C services/ops up`). Use `stack select`/`stack init` per environment.
- Containerized flow: `docker build -t pulumi-yaml-aci .` then run `docker run --rm -v $(pwd):/workspace pulumi-yaml-aci -C services/container-group preview -s dev` (same image works for every project).
- When ARM foundations change (new subnet/KV/workspace), update only `env/Pulumi.<env>.yaml` and redeploy downstream stacks to consume the refreshed outputs.

## Conventions & Pitfalls
- No resources belong in `env`; it is a contract-only stack so environment promotion stays deterministic.
- Keep `azure-infra/containerGroup.json` and `.bicep` synchronized; the JSON file is what gets deployed.
- The Docker image copies only `env/`, `services/`, and `azure-infra/`; place new assets under those directories or adjust the `Dockerfile`.
- Use ASCII identifiers/tags and simple interpolations (e.g., `${name}-dns`) to match the ARM template assumptions.

## Extending the Catalog
- Add new services under `services/<name>` that (1) reference `env`, (2) load their ARM/Bicep template from `azure-infra/`, and (3) expose outputs consumable by other stacks.
- Surface any new shared values by augmenting `env` outputs first, then consume them via stack references instead of copying config between services.
- New environments only require new `Pulumi.<env>.yaml` files plus `pulumi stack init <env>` in each project; code should stay identical across stacks.
