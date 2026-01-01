# Pulumi YAML-First Multi-Cloud Template

A **catalog-style** mono-repo for deploying cloud services with Pulumi YAML. Configuration is layered: global per-environment facts by provider, service-specific overrides next to each service.

## Layout

```
services/
├── config/                              # Global per-environment config (human-edited)
│   ├── azure/                           # Azure-specific global config
│   │   ├── Pulumi.dev.yaml
│   │   └── Pulumi.prod.yaml
│   ├── aws/                             # (future) AWS-specific global config
│   └── gcp/                             # (future) GCP-specific global config
├── azure/                               # Azure services
│   ├── stateless/                       # Stateless services (can be destroyed/recreated)
│   │   └── az-app1/
│   │       ├── Pulumi.yaml              # Project definition
│   │       ├── override.Pulumi.dev.yaml # Service overrides (human-edited)
│   │       └── Pulumi.dev.yaml          # (auto-generated - DO NOT EDIT)
│   └── stateful/                        # Stateful services (databases, storage, etc.)
├── aws/                                 # (future) AWS services
└── gcp/                                 # (future) GCP services
shared/                                  # Shared assets
├── arm/                                 # ARM/Bicep templates
├── scripts/                             # Helper scripts, executables
└── policies/                            # Azure Policy definitions, etc.
catalog.yaml                             # Service registry
pulumiw.py                               # Wrapper that merges config and runs Pulumi
```

## Service Categories

| Category | Location | Purpose |
|----------|----------|---------|
| **Stateless** | `services/<provider>/stateless/` | Services that can be destroyed and recreated without data loss (compute, networking) |
| **Stateful** | `services/<provider>/stateful/` | Services with persistent data (databases, storage accounts, key vaults) |

## Configuration Strategy

| File | Location | Who edits | Purpose |
|------|----------|-----------|---------|
| `services/config/<provider>/Pulumi.<stack>.yaml` | Config folder | Humans | Global environment facts per provider |
| `override.Pulumi.<stack>.yaml` | Service folder | Humans | Per-service overrides |
| `Pulumi.<stack>.yaml` | Service folder | **pulumiw.py** | Auto-generated — **DO NOT EDIT** |

### Rules of the Road
- **Edit only:**
  - `services/config/<provider>/Pulumi.<stack>.yaml` — global config per provider/env
  - `services/<provider>/*/<service>/override.Pulumi.<stack>.yaml` — service overrides
- **Never hand-edit:**
  - `services/<provider>/*/<service>/Pulumi.<stack>.yaml` (regenerated on each run)

## Quick Start

```bash
# 1. Login to Pulumi
pulumi login

# 2. Preview a service
./pulumiw.py dev az-app1 preview

# 3. Deploy a service
./pulumiw.py dev az-app1 up

# 4. Deploy all services
./pulumiw.py dev all up
```

## What `pulumiw.py` Does

1. Looks up service in `catalog.yaml` to find path and provider
2. Reads global vars from `services/config/<provider>/Pulumi.<stack>.yaml`
3. Merges in service overrides from `<service>/override.Pulumi.<stack>.yaml`
4. Maps merged vars to Pulumi config keys (project-namespaced)
5. Writes the result to `<service>/Pulumi.<stack>.yaml` (with header comment)
6. Runs the requested Pulumi command (`preview`, `up`, `destroy`, etc.)

## Catalog Format

```yaml
# catalog.yaml
services:
  - name: az-app1
    path: services/azure/stateless/az-app1
    provider: azure           # Determines which config folder to use
    type: stateless           # Documentation: stateless or stateful
    description: "Empty resource group (starter service)"
  
  - name: az-storage
    path: services/azure/stateful/az-storage
    provider: azure
    type: stateful
    description: "Storage account with blob containers"
```

## Adding a New Service

1. Choose the appropriate category:
   ```bash
   # Stateless service
   mkdir -p services/azure/stateless/my-service
   
   # Stateful service
   mkdir -p services/azure/stateful/my-service
   ```

2. Add `Pulumi.yaml`:
   ```yaml
   name: my-service
   runtime: yaml
   description: "My new service"
   
   config:
     my-service:location:
       type: string
     my-service:resourceGroupName:
       type: string
     my-service:tags:
       type: object
   
   resources:
     rg:
       type: azure-native:resources:ResourceGroup
       properties:
         resourceGroupName: ${my-service:resourceGroupName}
         location: ${my-service:location}
         tags: ${my-service:tags}
   
   outputs:
     resourceGroupName: ${rg.name}
   ```

3. (Optional) Add override files:
   ```yaml
   # override.Pulumi.dev.yaml
   resourceGroupName: rg-custom-my-service-dev
   tags:
     app: my-service
   ```

4. Register in `catalog.yaml`:
   ```yaml
   services:
     - name: my-service
       path: services/azure/stateless/my-service
       provider: azure
       type: stateless
       description: "My new service"
   ```

5. Deploy:
   ```bash
   ./pulumiw.py dev my-service up
   ```

## Adding a New Provider

1. Create config folder:
   ```bash
   mkdir -p services/config/aws
   ```

2. Create global config:
   ```yaml
   # services/config/aws/Pulumi.dev.yaml
   env: dev
   region: us-east-1
   
   aws:
     accountId: "123456789012"
   
   tags:
     env: dev
     owner: team-name
   ```

3. Create service folders:
   ```bash
   mkdir -p services/aws/stateless services/aws/stateful
   ```

4. Register services with `provider: aws` in catalog.

## Shared Assets

The `shared/` folder stores reusable assets that aren't Pulumi projects:

| Folder | Purpose |
|--------|---------|
| `shared/arm/` | ARM/Bicep templates referenced by Pulumi deployments |
| `shared/scripts/` | Helper scripts, CLIs, executables |
| `shared/policies/` | Azure Policy, OPA policies, governance definitions |

Example usage in a Pulumi YAML project:
```yaml
resources:
  deployment:
    type: azure-native:resources:Deployment
    properties:
      properties:
        template:
          fn::fromJSON:
            fn::file: ${pulumi.cwd}/../../shared/arm/myTemplate.json
```

## Global Config Example

```yaml
# services/config/azure/Pulumi.dev.yaml
env: dev
location: westeurope

azure:
  tenantId: "00000000-0000-0000-0000-000000000000"
  subscriptionId: "11111111-1111-1111-1111-111111111111"

naming:
  prefix: myorg

tags:
  env: dev
  owner: team-name
```

## Service Override Example

```yaml
# services/azure/stateless/az-app1/override.Pulumi.dev.yaml
resourceGroupName: rg-custom-az-app1-dev
tags:
  app: az-app1
  cost-center: engineering
```

