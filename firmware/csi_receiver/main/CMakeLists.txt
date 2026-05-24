# =============================================================================
# firmware/csi_receiver/main/CMakeLists.txt
# Registers source files with the ESP-IDF build system.
# Every .c file you add to main/ must be listed here.
# =============================================================================

idf_component_register(
    SRCS
        "main.c"
        "wifi_csi.c"
    INCLUDE_DIRS
        "."
    REQUIRES
        # ESP-IDF components this project depends on
        nvs_flash        # Non-volatile storage — required for WiFi calibration data
        esp_wifi         # WiFi driver — provides CSI callback API
        esp_netif        # Network interface abstraction layer
        esp_event        # Event loop — WiFi connects/disconnects via events
        esp_timer        # High-resolution timer for CSI timestamps
)
