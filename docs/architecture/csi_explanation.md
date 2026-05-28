# WiFi CSI Explanation

## What is CSI?

**Channel State Information (CSI)** describes how a wireless channel affects transmitted OFDM subcarriers. Human motion perturbs multipath components, introducing measurable temporal changes in CSI amplitudes/phases.

## Why CSI for HAR?

Compared with camera-based sensing, CSI-based sensing can be:

- privacy-preserving (no visual capture)
- low-cost (commodity WiFi hardware)
- robust in low-light and through-light-obstruction scenarios

## CSI in This Project

- ESP32-S3 firmware captures CSI data.
- CSI packets are transmitted via UART to host scripts.
- The pipeline processes amplitudes into windows and feature vectors.
- A classifier maps features to activity labels.

## Practical Notes

- Keep transmitter/receiver geometry stable during data collection.
- Collect multiple sessions per activity for generalization.
- Maintain balanced classes to reduce prediction bias.
