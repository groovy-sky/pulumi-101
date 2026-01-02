# Copilot Instructions

## Repo Fundamentals
- Catalog-style Pulumi YAML repo. `pulumiw.py` merges provider-level config with per-service overrides and runs Pulumi commands.
- `roles/env` is a contract-only stack (no resources). It mirrors real ARM identifiers so every downstream service can reference them deterministically.
- `services/<provider>/` holds two things: (1) global per-stack config files (`Pulumi.dev.yaml`, etc.) and (2) actual Pulumi YAML projects under `stateless/` and `stateful/`.
- Each service folder contains a hand-authored `Pulumi.yaml`, optional `override.Pulumi.<stack>.yaml`, and an auto-generated `Pulumi.<stack>.yaml`. Never edit the generated file directly.
- `shared/arm`, `shared/policies`, and `shared/scripts` store reusable assets. Reference them via `fn::file`/`fn::fromJSON` rather than duplicating templates.

## Configuration & Stack References
- Config layering order: provider global file ➜ service overrides ➜ generated stack file. Let `pulumiw.py` write the final config.
- Use the `projectConfig` block inside `services/<provider>/Pulumi.<stack>.yaml` to push shared values (e.g., `envStackRef`, workspace IDs) into every service automatically. `map_vars_to_pulumi_config()` emits them as `projectName:<key>` entries.
- Stack references: expose values from `roles/env` (or another service), add a config key for the target stack name, and consume it via `new pulumi.StackReference(config.require("<project>:stackKey"))` inside the service code. This keeps shared identifiers centralized and versioned.
- When adding new ARM-provided IDs, update `roles/env/Pulumi.<stack>.yaml` first, then update `projectConfig` to distribute them. Avoid recomputing those values in service code.
- Keep service-level knobs (names, SKUs, tags, ports, etc.) in config. YAML programs should stay generic and pull behavior from config entries.
- Secrets must be set with `pulumi config set --secret ...` so encrypted values land in the generated files.

## Resource Patterns
- Prefer a `variables:` block in Pulumi YAML for derived strings (e.g., `${name}-dns`, subnet IDs) so you do not repeat interpolation logic across resources.
- When replaying ARM/Bicep, load JSON templates with `fn::file` + `fn::fromJSON` and pass parameters exactly as defined in the template schema.
- Outputs should remain human-friendly (names, IDs, URIs) to make downstream stack references straightforward.

## Workflows & Commands
- Standard flow: `pulumi login`, then `./pulumiw.py <stack> <service> preview|up|destroy`. `--generate-only` regenerates config without invoking Pulumi.
- `catalog.yaml` is the single source of truth for deployable services. Add new entries there whenever you create a project.
- When foundation values change (new subnet, KV, workspace, etc.), update `roles/env/Pulumi.<stack>.yaml`, regenerate configs with `pulumiw.py`, and redeploy consumers.
- Container usage is optional. The supplied `Dockerfile` copies IaC directories into a Pulumi CLI image—update its `COPY` directives if you move assets outside `roles/`, `services/`, or `shared/`.

## Extending the Catalog
- To add a service: scaffold a Pulumi YAML project under `services/<provider>/<statefulness>/<name>`, define required config in `Pulumi.yaml`, register it in `catalog.yaml`, and rely on global config + overrides for per-env settings.
- Introduce new shared values by (1) adding them to `roles/env` outputs, (2) surfacing them through `projectConfig`, and (3) consuming them via stack references—never duplicate literals across services.
- New environments only require new `Pulumi.<env>.yaml` files plus `pulumi stack init <env>` in each project; the YAML programs remain identical across stacks.
