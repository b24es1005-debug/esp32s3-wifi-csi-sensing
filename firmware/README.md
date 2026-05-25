# Firmware (ESP-IDF) — build instructions

This folder is the ESP-IDF project root for the `csi_receiver` firmware.

Project wiring
- `firmware/CMakeLists.txt` is the ESP-IDF top-level project file.
- `firmware/csi_receiver/main` is added through `EXTRA_COMPONENT_DIRS` so `main.c` is compiled and `app_main()` is linked.

Prerequisites
- ESP-IDF installed and `export.sh` sourced (sets `IDF_PATH` and updates PATH).
- Xtensa/RISC-V toolchain for ESP32-S3 available via ESP-IDF or separately.

Quick build
```bash
cd firmware
. $IDF_PATH/export.sh   # or `. ~/esp/esp-idf/export.sh` depending on your install
idf.py set-target esp32s3
idf.py menuconfig      # optional — adjust sdkconfig
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

Clean stale build artifacts
```bash
cd firmware
rm -rf build
rm -f CMakeCache.txt
rm -f sdkconfig sdkconfig.old
# Also remove nested build folder if present
rm -rf csi_receiver/build
rm -f csi_receiver/sdkconfig csi_receiver/sdkconfig.old
```

Notes
- This repo uses `firmware/CMakeLists.txt` as the ESP-IDF top-level CMake file.
- If you previously built from `firmware/csi_receiver`, remove stale caches and rebuild from `firmware/`.
- If the build picks `/usr/bin/cc`, ensure you sourced `export.sh` correctly and that `xtensa-esp32s3-elf-gcc` is on your PATH.
- If you see `undefined reference to app_main`, clean the build directory and rebuild from `firmware/` so the `csi_receiver/main` component is re-discovered.
- Current low-memory defaults: `CSI_MAX_SUBCARRIERS=52`, `CSI_QUEUE_LENGTH=8`, `CSI_TASK_STACK_SIZE=2048` words.
- Increase those values only if you have verified there is enough free DRAM/PSRAM for your exact capture setup.
