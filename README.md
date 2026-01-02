# Pulumi YAML-First Template

Run many Pulumi YAML projects from one catalog. Global config lives once per provider/environment, each service only overrides what it needs, and `pulumiw.py` glues it all together.

## Repo Layout

- `catalog.yaml` — registry of services with provider, path, and type
- `pulumiw.py` — wrapper that merges config then runs Pulumi for you
- `services/<provider>/Pulumi.<stack>.yaml` — global facts (location, tags, stack refs)
- `services/<provider>/<statefulness>/<service>/` — individual Pulumi YAML projects
- `shared/` — reusable ARM/Bicep, scripts, and policies
- `roles/env/` — contract-only stack that surfaces ARM-managed IDs

## Config Layering

1. Global config: `services/<provider>/Pulumi.<stack>.yaml`
2. (Optional) per-service overrides: `<service>/override.Pulumi.<stack>.yaml`
3. Generated file: `<service>/Pulumi.<stack>.yaml` (never edit by hand)

`pulumiw.py` performs the merge, writes the generated file with the right `projectName:<key>` entries, ensures the Pulumi stack exists, and runs `preview`, `up`, etc.

## Everyday Workflow

```bash
pulumi login
./pulumiw.py dev az-app1 preview   # or up/destroy
./pulumiw.py dev all up            # deploy everything listed in catalog
```

Key points:
- Always edit the provider-level files and overrides, never the generated stack files.
- Use `./pulumiw.py dev <service> --generate-only` when you just want to refresh config.
- `catalog.yaml` is the single source of truth for what can be deployed.

## Adding a Service

1. Create a folder under `services/<provider>/(stateless|stateful)/<name>` and add a Pulumi YAML project.
2. Register it in `catalog.yaml`.
3. Adjust global config (`location`, `tags`, stack references) in `services/<provider>/Pulumi.<stack>.yaml`.
4. Add overrides only when the service needs to deviate from the global defaults.
5. Run `./pulumiw.py <stack> <service> up`.

## Mapping Values Between Projects

- Publish shared identifiers (subscription IDs, subnet IDs, Key Vault URIs, etc.) from `roles/env` outputs.
- In each provider config file add a `projectConfig` section to push shared values into every service’s config automatically:

```yaml
projectConfig:
  envStackRef: your-org/env/dev
  logAnalyticsWorkspaceId: /subscriptions/.../workspaces/log-platform-dev
```

`map_vars_to_pulumi_config()` turns those keys into `projectName:envStackRef`, `projectName:logAnalyticsWorkspaceId`, etc., so every service receives the same values without touching local overrides.
- When one service depends on another, expose outputs from the producer, store the stack name under `projectConfig`, and read it via `new pulumi.StackReference(config.require("<project>:otherStackRef"))` in code.

## Shared Assets

Place any reusable ARM/Bicep files under `shared/arm/`, scripts under `shared/scripts/`, and governance artifacts under `shared/policies/`. Reference them from Pulumi YAML with `fn::file` and `fn::fromJSON`.

## Need Another Provider?

Add `services/aws` or `services/gcp`, create their own `Pulumi.<stack>.yaml` files, and register services with `provider: aws` or `provider: gcp` in the catalog. The same wrapper workflow applies.

That’s it: keep globals tidy, overrides tiny, and let `pulumiw.py` handle the rest.

