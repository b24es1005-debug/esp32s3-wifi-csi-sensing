/* fw_config.h
 * Firmware configuration header for CSI receiver.
 * Add compile-time feature flags and versioning here.
 */

#pragma once

/* Protocol / format version emitted on UART lines. Increment if CSV layout
 * changes in a non-backwards-compatible way. */
#define CSI_FORMAT_VERSION 1

/* Enable periodic diagnostic lines over UART (DIAG,...) for dataset quality
 * monitoring. Disabled by default to preserve existing behavior. */
#define ENABLE_DIAG_LINES 0

/* Interval (ms) between diagnostic lines when enabled */
#define DIAG_INTERVAL_MS 5000

/* Include MAC address in CSI CSV output (0 = omit, 1 = include). Disabled
 * by default to keep UART bandwidth low. */
#define INCLUDE_MAC_IN_CSV 0
