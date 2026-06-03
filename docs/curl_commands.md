# Curl Commands
The following three `curl` commands were used in the Docker environment to manually simulate the API requests made by the TRMNL device and to verify server response behavior.

## Placeholders
[IP] should be replaced with your IP address.  
[TOKEN] should be replaced with the access token returned by the setup call.

## Setup Call
```
curl -X GET "http://[IP]:8069/api/setup/" \
  -H "ID: AA:BB:CC:DD:EE:FF" \
  -H "FW-Version: 1.5.2"
```

## Display Call
```
curl -X GET "http://[IP]:8069/api/display" \
  -H "ID: AA:BB:CC:DD:EE:FF" \
  -H "Access-Token: [TOKEN]" \
  -H "Refresh-Rate: 1800" \
  -H "Battery-Voltage: 4.1" \
  -H "FW-Version: 1.5.2" \
  -H "RSSI: -69" \
  -H "Width: 800" \
  -H "Height: 480"
```

## Log Call
```
curl -X POST "http://[IP]:8069/api/log" \
  -H "ID: AA:BB:CC:DD:EE:FF" \
  -H "Access-Token: [TOKEN]" \
  -H "Accept: application/json, */*" \
  -H "Content-Type: application/json" \
  -d '{
    "logs": [
      {
        "created_at": 1745000000,
        "id": 42,
        "message": "Image render failed: unexpected EOF",
        "source_line": 318,
        "source_path": "src/bl.cpp",
        "wifi_signal": -67,
        "wifi_status": "Connected",
        "refresh_rate": 1800,
        "sleep_duration": 145,
        "firmware_version": "1.5.2",
        "special_function": "None",
        "battery_voltage": 3.95,
        "wake_reason": "Timer",
        "free_heap_size": 48320,
        "max_alloc_size": 38912
      }
    ]
  }'
```
