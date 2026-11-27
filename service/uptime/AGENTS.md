You are an expert technical writer for this project.

## Requirement
- design and develop a golang application to use snmp poll to device and generate device reboot event
- target devices are SNMP enabled from multiple vendors such as Huawei, ZTE, Fiberhome, Nokia, etc...
- target devices are around 25,000 devices
- device list stored in postgresql table device (SQL: select ip, name from device)
- polling agent must load and save list of target devices to file so that it continue to poll eventhoug postgres is not accessible
- save state using leveldb
- polling will be start every 15 minutes interval using cron
- able to handle following scenarios:
  - sysUptime roll-up due to overflow
  - sysUptime stay at MAX value due to some device firmware bugs
- suggest polling strategy, any missing scenarios or error handling

## Dev environment
- build for linux x86
