/* =============================================================================
 * main.c
 * Save to: firmware/csi_receiver/main/main.c
 *
 * Entry point for the ESP32-S3 CSI receiver firmware.
 * app_main() is called by the ESP-IDF startup code after:
 *   - Flash cache is initialised
 *   - FreeRTOS scheduler is started
 *   - Both cores are running
 *
 * Responsibilities:
 *   1. Initialise NVS (required for WiFi to store calibration data)
 *   2. Initialise the TCP/IP stack (required for WiFi)
 *   3. Create the default event loop (required for WiFi events)
 *   4. Call wifi_csi_init() which does everything else
 *
 * Why so little code here?
 *   Good embedded architecture separates concerns. main.c owns startup
 *   sequencing only. All WiFi, CSI, and serial logic lives in wifi_csi.c.
 *   This makes wifi_csi.c fully testable without touching main.c.
 * =============================================================================
 */

#include "esp_log.h"
#include "esp_err.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "wifi_csi.h"

static const char *TAG = "MAIN";

/* ---------------------------------------------------------------------------
 * app_main — ESP-IDF entry point
 *
 * Called once from the main task (stack: 3584 bytes, priority: 1, core: 0).
 * We do NOT call vTaskDelete(NULL) at the end — app_main can safely return,
 * at which point the main task is deleted by the scheduler.
 * --------------------------------------------------------------------------- */
void app_main(void)
{
    ESP_LOGI(TAG, "=================================================");
    ESP_LOGI(TAG, " ESP32-S3 WiFi CSI Sensing System");
    ESP_LOGI(TAG, " Firmware built: " __DATE__ " " __TIME__);
    ESP_LOGI(TAG, "=================================================");

    /* ── Step 1: Non-Volatile Storage ─────────────────────────────────────
     * NVS stores WiFi calibration data, PHY parameters, and (in later phases)
     * our own configuration. It must be initialised before esp_wifi_init().
     *
     * If NVS has no free pages or was written by an older firmware version,
     * erase and reinitialise. Data loss is acceptable here (it's calibration,
     * not user data). */
    esp_err_t nvs_ret = nvs_flash_init();
    if (nvs_ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        nvs_ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS needs erase — erasing and reinitialising");
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_ret);
    ESP_LOGI(TAG, "NVS initialised");

    /* ── Step 2: TCP/IP network stack ─────────────────────────────────────
     * esp_netif_init() initialises the underlying LwIP TCP/IP stack.
     * This must be called before any WiFi or network operations. */
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_LOGI(TAG, "TCP/IP stack initialised");

    /* ── Step 3: Default event loop ───────────────────────────────────────
     * The event loop dispatches WiFi events (connected, disconnected, got IP)
     * to our handlers in wifi_csi.c.
     * Must be created before esp_wifi_init(). */
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    ESP_LOGI(TAG, "Event loop created");

    /* ── Step 4: WiFi + CSI initialisation ────────────────────────────────
     * This call creates the FreeRTOS queue, spawns the processing task,
     * connects to WiFi, and enables the CSI callback.
     * After this returns, CSI data is flowing automatically. */
    wifi_csi_init();

    ESP_LOGI(TAG, "System running — CSI lines appearing on UART0");
    ESP_LOGI(TAG, "Open Python visualizer: python3 python/visualizer.py");

    /* app_main can return — the processing task keeps running */
}
