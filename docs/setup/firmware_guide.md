# Firmware Guide (ESP32-S3 CSI Receiver)

This document explains the firmware-side role in the RF sensing pipeline.

## Firmware Role

The firmware running under `firmware/csi_receiver/` is responsible for:

- configuring ESP32-S3 WiFi CSI reception
- capturing CSI packets from the RF channel
- formatting CSI packets for UART serial streaming
- providing input to host-side logging and ML inference

## Build and Flash

```bash
cd firmware/csi_receiver
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

## Expected Behavior

After successful flash, host-side Python scripts should read lines beginning with `CSI,` over serial.

## Integration Notes

- Host scripts in `python/` and `ml/` assume UART baud `115200`
- Keep USB data cable stable during long recordings
- Use consistent AP and room setup for repeatable datasets

## Verification

Use the serial reader:

```bash
source .venv/bin/activate
cd python
python serial_reader.py --port /dev/ttyACM0 --baud 115200 --duration 30 --verbose
```
