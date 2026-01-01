pulumi login
pulumi -C env stack init dev
pulumi -C env up
pulumi -C azure/container-group stack init dev
pulumi -C azure/container-group config set envStackRef your-org/env/dev
pulumi -C azure/container-group up
# Pulumi YAML-First Azure Template

The repo now follows a catalog pattern: a centralized `env` project exposes ARM-provisioned foundations, while each service lives in its own Pulumi YAML project and consumes the shared contract through stack references. ARM remains the source of truth for raw infrastructure (captured under `shared/`).

## Layout

```
env/                     # Central environment contract (formerly arm-bridge)
azure/
└── container-group/     # Deploys ACI workload via shared ARM template
shared/
├── containerGroup.json  # Authoritative ARM template
└── containerGroup.bicep # Readable Bicep source kept in sync with JSON
Dockerfile               # Pulumi CLI container that ships env + azure services + shared templates
README.md
```

## Project Responsibilities

- `env`: surfaces subscription, resource group, subnet, Log Analytics, and Key Vault identifiers. No resources are created—config in `Pulumi.<env>.yaml` mirrors ARM and emits friendly outputs for consumers.
- `azure/container-group`: consumes `env` via `pulumi:pulumi:StackReference`, replays `shared/containerGroup.json` with service-specific parameters, and outputs container group identifiers/FQDN.

## Configuration Strategy

- Centralize environment-specific facts in `env/Pulumi.<stack>.yaml`. Update only these files when ARM foundations change.
- Services keep their own `Pulumi.<stack>.yaml`, but the first config key is always `envStackRef` (or another catalog reference). Example: `envStackRef: your-org/env/dev`.
- When services depend on peers, add more stack reference configs (e.g., `containerGroupStackRef`) and avoid hard-coded IDs.
- Continue using `pulumi config set --secret` for any sensitive values so they stay encrypted in stack files.

## Running the Stacks

1. Bootstrap the environment contract:
	 ```bash
	 pulumi -C env stack select dev    # or init dev
	 pulumi -C env up
	 ```
2. Deploy a catalog service such as the container group:
	 ```bash
	 pulumi -C azure/container-group stack select dev
	 pulumi -C azure/container-group config set envStackRef your-org/env/dev
	 pulumi -C azure/container-group up
	 ```
Repeat the same flow for `staging` or `prod`; only stack config values change.

## Docker Workflow

Build once, run anywhere:

```bash
docker build -t pulumi-yaml-aci .

# Preview the container-group service for dev inside the container
docker run --rm -v $(pwd):/workspace pulumi-yaml-aci \
	-C azure/container-group preview -s dev

# Deploy env from the containerized CLI
docker run --rm -v $(pwd):/workspace pulumi-yaml-aci \
	-C env up -s dev
```

## Outputs & Visibility

- `env` exports the canonical Azure identifiers; update its config whenever ARM foundations move.
- `azure/container-group` exports `resourceGroupName`, `containerGroupName`, `containerGroupId`, and `fqdn` for downstream consumers.

## Next Steps

1. Replace placeholder IDs in `env/Pulumi.<env>.yaml` with real subscription/resource values.
2. Update service stack configs (`azure/*/Pulumi.<env>.yaml`) with your Pulumi org and any workload-specific knobs.
3. Extend the catalog by adding more service folders under `azure/`, keeping shared ARM/Bicep assets under `shared/`, and wiring each service to the central `env` stack.

