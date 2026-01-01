# ARM/Bicep Templates

Store reusable ARM JSON and Bicep templates here.

## Usage

Reference templates from Pulumi YAML projects:

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
