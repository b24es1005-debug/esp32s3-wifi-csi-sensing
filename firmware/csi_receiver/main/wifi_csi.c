/* =============================================================================
 * wifi_csi.c
 * Save to: firmware/csi_receiver/main/wifi_csi.c
 *
 * WiFi CSI capture implementation for ESP32-S3 with ESP-IDF v5.2.
 *
 * Architecture:
 *   WiFi driver task (priority 23)
 *     └─► csi_callback()          [IRAM, ISR-safe, < 10 µs]
 *           └─► xQueueSendFromISR()
 *                 └─► g_csi_queue  [32 slots, DRAM]
 *                       └─► csi_processing_task() [priority 5, core 1]
 *                             └─► ets_printf() → UART → Python
 * =============================================================================
 */

#include "wifi_csi.h"

#include <math.h>
#include <string.h>
#include <stdio.h>
#include <inttypes.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/event_groups.h"

#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_err.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "rom/ets_sys.h"   /* ets_printf — writes directly to UART0 hardware */

static const char *TAG = "WIFI_CSI";

/* Global queue handle — defined here, declared extern in wifi_csi.h */
QueueHandle_t g_csi_queue = NULL;

/* Event group bit: set when WiFi associates with the AP */
#define WIFI_CONNECTED_BIT BIT0
static EventGroupHandle_t s_wifi_event_group = NULL;

/* Throttle counter — only emit every CSI_THROTTLE_EVERY packets */
static volatile uint32_t s_packet_count = 0;

/* Callback-level statistics (best-effort, lock-free) */
static volatile uint32_t s_cb_ok_packets      = 0;
static volatile uint32_t s_cb_drop_invalid    = 0;
static volatile uint32_t s_cb_drop_queue_full = 0;

/* ===========================================================================
 * SECTION 1: WiFi event handler
 *
 * ESP-IDF WiFi sends events to the default event loop.
 * We handle CONNECTED / DISCONNECTED / GOT_IP here.
 * =========================================================================== */
static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                                int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT) {
        switch (event_id) {
            case WIFI_EVENT_STA_START:
                /* WiFi stack started — now attempt to associate */
                ESP_LOGI(TAG, "WiFi STA started, connecting to AP...");
                esp_wifi_connect();
                break;

            case WIFI_EVENT_STA_CONNECTED:
                ESP_LOGI(TAG, "WiFi connected to AP");
                /* CSI capture begins receiving packets now */
                break;

            case WIFI_EVENT_STA_DISCONNECTED:
                ESP_LOGW(TAG, "WiFi disconnected, retrying...");
                esp_wifi_connect();
                break;

            default:
                break;
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

/* ===========================================================================
 * SECTION 2: CSI callback
 *
 * CRITICAL RULES — this function runs inside the WiFi driver task (prio 23):
 *   ✓ IRAM_ATTR — always resident in fast RAM, no cache miss latency
 *   ✓ Must return in < ~50 µs
 *   ✓ Only calls ISR-safe FreeRTOS functions (xQueueSendFromISR)
 *   ✗ No printf / ets_printf
 *   ✗ No malloc / free
 *   ✗ No vTaskDelay or any blocking call
 *   ✗ No esp_wifi_* calls (not reentrant from callback context)
 * =========================================================================== */
static void IRAM_ATTR csi_callback(void *ctx, wifi_csi_info_t *data)
{
    /* Guard against null/empty packets — can occur during association */
    if (!data || !data->buf || data->len == 0) {
        s_cb_drop_invalid++;
        return;
    }

    /* Sanity checks: CSI bytes must be imag+real pairs, and queue must exist */
    if ((data->len & 0x1) != 0 || g_csi_queue == NULL) {
        s_cb_drop_invalid++;
        return;
    }

    /* Throttle: only enqueue every Nth packet to cap output rate */
    uint32_t count = s_packet_count++;
    if ((count % CSI_THROTTLE_EVERY) != 0) {
        return;
    }

    /* Build the packet struct on the stack.
     * Zero-initialise so unused subcarrier slots are always 0. */
    csi_packet_t pkt;
    memset(&pkt, 0, sizeof(pkt));

    pkt.timestamp_us    = esp_timer_get_time();
    pkt.rssi            = data->rx_ctrl.rssi;
    pkt.num_subcarriers = (uint16_t)(data->len / 2);

    /* Copy MAC address (6 bytes) */
    memcpy(pkt.mac, data->mac, 6);

    /* Copy CSI buffer — clamp to our maximum to prevent overflow.
     * data->len is in bytes; each subcarrier = 2 bytes (imag + real). */
    uint16_t copy_bytes = data->len;
    if (copy_bytes > (uint16_t)sizeof(pkt.buf)) {
        copy_bytes = (uint16_t)sizeof(pkt.buf);
        pkt.num_subcarriers = CSI_MAX_SUBCARRIERS;
    }
    memcpy(pkt.buf, data->buf, copy_bytes);

    /* Send to queue — timeout=0 means DROP if full (never block WiFi task).
     * BaseType_t woken: set if a higher-prio task was unblocked by this send. */
    BaseType_t higher_prio_task_woken = pdFALSE;
    BaseType_t sent = xQueueSendFromISR(g_csi_queue, &pkt, &higher_prio_task_woken);
    if (sent != pdTRUE) {
        s_cb_drop_queue_full++;
        return;
    }
    s_cb_ok_packets++;

    /* If the queue send woke our processing task, yield to it immediately
     * rather than waiting for the next FreeRTOS tick. This minimises latency. */
    if (higher_prio_task_woken == pdTRUE) {
        portYIELD_FROM_ISR();
    }
}

/* ===========================================================================
 * SECTION 3: CSI processing task
 *
 * Runs on core 1 at priority 5. Blocks on the queue until a packet arrives,
 * computes amplitudes, and emits one CSV line over UART using ets_printf.
 *
 * Why ets_printf instead of printf?
 *   printf() routes through the VFS layer and acquires a mutex.
 *   If another task (e.g. ESP_LOGI) holds that mutex, printf blocks.
 *   ets_printf writes directly to UART0 hardware registers — always safe,
 *   never blocks, but also not thread-safe between multiple callers.
 *   Since this is the ONLY task writing CSI lines, ets_printf is correct.
 *
 * Output format (one line per packet):
 *   CSI,<timestamp_us>,<rssi>,<num_subcarriers>,<amp0>,<amp1>,...
 * =========================================================================== */
static void csi_processing_task(void *arg)
{
    csi_packet_t pkt;
    /* Amplitude array on the task stack — fine because CSI_TASK_STACK_SIZE
     * is 4096 words. Float array of 114 = 456 bytes — well within budget. */
    float amplitudes[CSI_MAX_SUBCARRIERS];

    /* Monitoring counters */
    uint32_t packets_processed = 0;
    uint32_t packets_dropped   = 0;
    int32_t rssi_min           = 0;
    int32_t rssi_max           = -100;
    int64_t rssi_sum           = 0;
#if ENABLE_DIAG_LINES
    int64_t last_diag_ts       = 0;
#endif

    ESP_LOGI(TAG, "CSI processing task running on core %d", xPortGetCoreID());

    for (;;) {
        /* Block here until the callback sends a packet.
         * CPU is returned to scheduler while waiting — zero busy-wait. */
        if (xQueueReceive(g_csi_queue, &pkt, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        uint16_t n = pkt.num_subcarriers;

        /* Sanity check: ignore packets with impossible subcarrier counts */
        if (n == 0 || n > CSI_MAX_SUBCARRIERS) {
            packets_dropped++;
            continue;
        }

        if (packets_processed == 0) {
            rssi_min = pkt.rssi;
            rssi_max = pkt.rssi;
        }
        if (pkt.rssi < rssi_min) {
            rssi_min = pkt.rssi;
        }
        if (pkt.rssi > rssi_max) {
            rssi_max = pkt.rssi;
        }
        rssi_sum += pkt.rssi;

        /* Compute amplitude for each subcarrier.
         * CSI buffer layout: [imag0, real0, imag1, real1, ...]
         * Amplitude = sqrt(real² + imag²)
         *
         * Note: sqrtf() is used (not sqrt) for float precision.
         * On ESP32-S3 Xtensa LX7, sqrtf uses the hardware FPU — fast. */
        for (uint16_t i = 0; i < n; i++) {
            float imag = (float)pkt.buf[2 * i];
            float real = (float)pkt.buf[2 * i + 1];
            amplitudes[i] = sqrtf(real * real + imag * imag);
        }

        /* Emit CSV line via ets_printf.
         * Format: CSI,<timestamp>,<rssi>,<num_sc>,<amp0>,<amp1>,...
         *
         * We deliberately omit the MAC address to keep lines shorter
         * and reduce UART load. Add ",mac" field back if needed for
         * multi-device setups in Phase 5. */
        ets_printf("CSI,%" PRId64 ",%d,%d",
                   pkt.timestamp_us,
                   (int)pkt.rssi,
                   (int)n);

        for (uint16_t i = 0; i < n; i++) {
          int amp_int = (int)(amplitudes[i] * 100.0f);
          ets_printf(",%d", amp_int);
        }
        ets_printf("\n");

        packets_processed++;

        /* Every 500 packets (~10 s at 50 Hz), log diagnostics to ESP_LOGI.
         * These appear in idf.py monitor but NOT in the Python serial reader
         * (because Python filters for lines starting with "CSI,"). */
        if (packets_processed % 500 == 0) {
            UBaseType_t queue_waiting = uxQueueMessagesWaiting(g_csi_queue);
            int32_t rssi_avg = (packets_processed > 0)
                ? (int32_t)(rssi_sum / (int64_t)packets_processed)
                : 0;
            ESP_LOGI(TAG, "Processed: %"PRIu32"  Dropped: %"PRIu32
                     "  Queue depth: %d/%d  RSSI[min/avg/max]=%"PRId32"/%"PRId32"/%"PRId32
                     "  CB[ok=%"PRIu32" invalid=%"PRIu32" qfull=%"PRIu32"]",
                     packets_processed, packets_dropped,
                     (int)queue_waiting, CSI_QUEUE_LENGTH,
                     rssi_min, rssi_avg, rssi_max,
                     s_cb_ok_packets, s_cb_drop_invalid, s_cb_drop_queue_full);

#if ENABLE_DIAG_LINES
            int64_t now_us = esp_timer_get_time();
            if (now_us - last_diag_ts >= (int64_t)DIAG_INTERVAL_MS * 1000) {
                int qd = (int)uxQueueMessagesWaiting(g_csi_queue);
                ets_printf("DIAG,%" PRId64 ",%" PRIu32 ",%" PRIu32 ",%d,%d\n",
                           now_us,
                           packets_processed,
                           packets_dropped,
                           qd,
                           CSI_FORMAT_VERSION);
                last_diag_ts = now_us;
            }
#endif
        }
    }
}

/* ===========================================================================
 * SECTION 4: WiFi initialisation
 *
 * Sets up the ESP-IDF WiFi stack in Station mode, registers the CSI callback,
 * and starts the connection process.
 * =========================================================================== */
static void wifi_init_sta(void)
{
    s_wifi_event_group = xEventGroupCreate();

    /* Create default WiFi station netif */
    esp_netif_create_default_wifi_sta();

    /* Initialise WiFi driver with default configuration.
     * WIFI_INIT_CONFIG_DEFAULT() sets safe values for all 40+ fields. */
    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));

    /* Register our event handler for WiFi and IP events */
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID,
        &wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP,
        &wifi_event_handler, NULL, NULL));

    /* Configure SSID and password */
    wifi_config_t wifi_config = {
        .sta = {
            .ssid     = CSI_WIFI_SSID,
            .password = CSI_WIFI_PASSWORD,
            /* threshold.authmode: accept WPA2 or stronger.
             * WIFI_AUTH_WPA2_PSK is correct for most home/office APs. */
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_LOGI(TAG, "WiFi init complete. Connecting to SSID: %s", CSI_WIFI_SSID);

    /* Wait until connected (or timeout after 30 s) */
    EventBits_t bits = xEventGroupWaitBits(
        s_wifi_event_group,
        WIFI_CONNECTED_BIT,
        pdFALSE,     /* do not clear on exit */
        pdFALSE,     /* wait for any bit */
        pdMS_TO_TICKS(30000)
    );

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "Connected to AP successfully");
    } else {
        ESP_LOGW(TAG, "WiFi connection timeout — CSI may still work from nearby APs");
    }
}

/* ===========================================================================
 * SECTION 5: CSI configuration and callback registration
 * =========================================================================== */
static void csi_init(void)
{
    /* Configure which frame types contribute CSI measurements.
     *
     * lltf_en (Legacy Long Training Field): always enable.
     *   Present in all 802.11a/g/n frames. 52 subcarriers in HT20.
     *
     * htltf_en (HT Long Training Field): enable for 802.11n frames.
     *   Provides additional measurements for HT (High Throughput) frames.
     *
     * stbc_htltf2_en: enable for STBC frames (Space-Time Block Coding).
     *   Mostly from access points with multiple antennas.
     *
     * ltf_merge_en: merge all LTF fields into one CSI result.
     *   Simplifies processing — you get one callback per frame instead of
     *   separate callbacks per LTF type.
     *
     * channel_filter_en: hardware channel smoothing.
     *   Set false for raw unsmoothed CSI — better for sensing.
     *   True would reduce variance but lose fine-grained channel detail.
     *
     * manu_scale: manual scaling. False = automatic (recommended).
     * shift: bit shift for manual scaling. Ignored when manu_scale=false. */
    wifi_csi_config_t csi_config = {
        .lltf_en           = true,
        .htltf_en          = true,
        .stbc_htltf2_en    = true,
        .ltf_merge_en      = true,
        .channel_filter_en = false,
        .manu_scale        = false,
        .shift             = 0,
    };

    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    wifi_promiscuous_filter_t filt = {
      .filter_mask =
          WIFI_PROMIS_FILTER_MASK_MGMT |
          WIFI_PROMIS_FILTER_MASK_DATA |
          WIFI_PROMIS_FILTER_MASK_CTRL
    };
    
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&filt));
    /* Register callback — called once per received WiFi frame with CSI data.
     * ctx (second arg) is user data pointer passed to callback; unused here. */
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_callback, NULL));
    
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));

    ESP_LOGI(TAG, "CSI capture enabled");
}

/* ===========================================================================
 * SECTION 6: Public init function — called from main.c
 * =========================================================================== */
void wifi_csi_init(void)
{
    /* ── Step 1: Create the inter-task queue ──────────────────────────────
     * uxQueueLength: how many csi_packet_t structs it can hold
     * uxItemSize:    size of each item in bytes (copied by value)
     *
     * We create this BEFORE starting WiFi so the callback always finds
     * a valid queue handle, even if it fires before our task starts. */
    g_csi_queue = xQueueCreate(CSI_QUEUE_LENGTH, sizeof(csi_packet_t));
    if (g_csi_queue == NULL) {
        ESP_LOGE(TAG, "Failed to create CSI queue — out of DRAM");
        /* In production firmware you'd restart or signal an error LED */
        abort();
    }
    ESP_LOGI(TAG, "CSI queue created (%d slots × %d bytes)",
             CSI_QUEUE_LENGTH, (int)sizeof(csi_packet_t));

    /* ── Step 2: Spawn processing task on core 1 ──────────────────────────
     * xTaskCreateStaticPinnedToCore allocates TCB and stack from our
     * own buffers, giving us control over which memory region they use.
     *
     * Stack from PSRAM (MALLOC_CAP_SPIRAM): the 8 MB PSRAM is perfect
     * for large task stacks — slower than DRAM (~40 ns vs ~10 ns) but
     * irrelevant for a 50 Hz processing task.
     *
     * TCB from internal DRAM (MALLOC_CAP_INTERNAL): the Task Control
     * Block is accessed by the scheduler on every context switch, so
     * it must be in fast DRAM. */
    StaticTask_t *tcb_buf   = heap_caps_malloc(sizeof(StaticTask_t),
                                                MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    StackType_t  *stack_buf = heap_caps_malloc(CSI_TASK_STACK_SIZE * sizeof(StackType_t),
                                                MALLOC_CAP_SPIRAM);

    if (!tcb_buf || !stack_buf) {
        ESP_LOGE(TAG, "Failed to allocate task buffers");
        abort();
    }

    TaskHandle_t task_handle = xTaskCreateStaticPinnedToCore(
        csi_processing_task,  /* task function                        */
        "csi_proc",           /* name for debugging (vTaskList)       */
        CSI_TASK_STACK_SIZE,  /* stack size in words                  */
        NULL,                 /* pvParameters — unused                */
        CSI_TASK_PRIORITY,    /* priority                             */
        stack_buf,            /* stack buffer                         */
        tcb_buf,              /* TCB buffer                           */
        CSI_TASK_CORE         /* core affinity                        */
    );

    if (task_handle == NULL) {
        ESP_LOGE(TAG, "Failed to create CSI processing task");
        abort();
    }
    ESP_LOGI(TAG, "CSI task started on core %d, priority %d",
             CSI_TASK_CORE, CSI_TASK_PRIORITY);

    /* ── Step 3: WiFi STA + CSI ───────────────────────────────────────── */
    wifi_init_sta();
    csi_init();
}
