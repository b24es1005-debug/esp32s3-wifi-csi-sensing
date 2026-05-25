/* =============================================================================
 * wifi_csi.h
 * Save to: firmware/csi_receiver/main/wifi_csi.h
 *
 * Public interface for the WiFi CSI capture module.
 * main.c includes this to call wifi_csi_init() and access the queue handle.
 * =============================================================================
 */

#pragma once

#include "fw_config.h"
#include <stdint.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_wifi_types.h"

/* ---------------------------------------------------------------------------
 * CONFIGURATION CONSTANTS
 * All tunable values are here so you never have to hunt through .c files.
 * --------------------------------------------------------------------------- */

/* WiFi credentials — replace with your AP details */
#define CSI_WIFI_SSID        "Kannaiya"
#define CSI_WIFI_PASSWORD    "19731618"

/* CSI capture is tuned conservatively for ESP32-S3 runtime stability.
 * HT20 gives 52 subcarriers, which is enough for most sensing experiments.
 * If you need larger captures later, increase this value carefully. */
#define CSI_MAX_SUBCARRIERS   52

/* FreeRTOS queue depth. 8 packets keeps memory use low and avoids
 * over-buffering on systems with smaller internal DRAM headroom. */
#define CSI_QUEUE_LENGTH      8

/* Processing task configuration */
#define CSI_TASK_STACK_SIZE   2048  /* words — PSRAM preferred, fallback allowed */
#define CSI_TASK_PRIORITY     5     /* below WiFi (23), above idle (0) */
#define CSI_TASK_CORE         1     /* core 1 — WiFi stack runs on core 0 */

/* Packet throttle: only output every Nth packet over serial.
 * At 100 Hz input and throttle=2, output rate ≈ 50 Hz.
 * Increase to reduce UART load; decrease for higher resolution. */
#define CSI_THROTTLE_EVERY   2

/* UART baud rate — must match Python serial_reader.py */
#define CSI_UART_BAUD        115200

/* ---------------------------------------------------------------------------
 * PACKET STRUCT
 * This struct is what travels through the FreeRTOS queue.
 * The CSI buffer is copied by value so the WiFi driver can immediately
 * reclaim its internal buffer after the callback returns.
 * --------------------------------------------------------------------------- */
typedef struct {
    int64_t  timestamp_us;                   /* esp_timer_get_time() at capture */
    int8_t   rssi;                           /* received signal strength (dBm)  */
    uint8_t  mac[6];                         /* transmitter MAC address         */
    uint16_t num_subcarriers;               /* number of valid subcarrier pairs */
    int8_t   buf[CSI_MAX_SUBCARRIERS * 2];  /* [imag0,real0, imag1,real1, ...]  */
} csi_packet_t;

/* ---------------------------------------------------------------------------
 * PUBLIC API
 * --------------------------------------------------------------------------- */

/* Call once from app_main() after nvs_flash_init() and esp_netif_init().
 * Creates the FreeRTOS queue, spawns the processing task,
 * initialises WiFi in STA mode, and registers the CSI callback. */
esp_err_t wifi_csi_init(void);

/* Queue handle exposed so other modules can peek at queue depth for debugging */
extern QueueHandle_t g_csi_queue;
