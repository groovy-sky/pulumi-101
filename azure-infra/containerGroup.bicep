param name string
param location string
param image string
param port int
param cpuCores int
param memoryInGb int
@allowed([
  'Always'
  'OnFailure'
  'Never'
])
param restartPolicy string = 'Always'
param zone string = ''
param tags object = {}

var zoneArray = empty(zone) ? [] : [zone]
var appliedZones = empty(zoneArray) ? null : zoneArray

resource containerGroup 'Microsoft.ContainerInstance/containerGroups@2023-05-01' = {
  name: name
  location: location
  tags: tags
  zones: appliedZones
  properties: {
    osType: 'Linux'
    restartPolicy: restartPolicy
    containers: [
      {
        name: name
        properties: {
          image: image
          resources: {
            requests: {
              cpu: cpuCores
              memoryInGb: memoryInGb
            }
          }
          ports: [
            {
              protocol: 'TCP'
              port: port
            }
          ]
        }
      }
    ]
    ipAddress: {
      type: 'Public'
      dnsNameLabel: '${name}-dns'
      ports: [
        {
          protocol: 'TCP'
          port: port
        }
      ]
    }
  }
}

output containerGroupName string = containerGroup.name
output containerGroupId string = containerGroup.id
output dnsNameLabel string = containerGroup.properties.ipAddress.dnsNameLabel
output fqdn string = containerGroup.properties.ipAddress.fqdn
