"""
visualizer.py
Save to: python/visualizer.py

Real-time CSI dashboard with 4 live panels.

Panel layout:
  ┌────────────────────────────┬──────────────┐
  │ [1] Subcarrier amplitudes  │ [2] Motion   │
  │     (current + smoothed)   │     state    │
  ├────────────────────────────┴──────────────┤
  │ [3] Amplitude heatmap (subcarrier × time) │
  ├───────────────────────────────────────────┤
  │ [4] Rolling variance + RSSI               │
  └───────────────────────────────────────────┘

Usage:
    Live hardware mode:
        python3 visualizer.py
        python3 visualizer.py --port /dev/ttyUSB0

    CSV replay mode (no hardware needed):
        python3 visualizer.py --csv ../data/csi_20240101_120000.csv

    Tune detection thresholds:
        python3 visualizer.py --motion-threshold 0.8 --presence-threshold 0.2

Architecture:
    Thread 1 (reader_thread) — serial/CSV read → packet queue
    Thread 2 (main)          — matplotlib FuncAnimation (must be main thread)

Why two threads?
    matplotlib's animation loop is blocking and must own the main thread.
    Serial readline() is also blocking. Without threading the GUI freezes
    between every packet. The queue decouples them cleanly.
"""

import sys
import time
import queue
import threading
import argparse
import logging
from collections import deque

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.animation import FuncAnimation
from matplotlib.patches import FancyBboxPatch

import serial
import pandas as pd

from utils import (
    validate_csi_line,
    parse_csi_line,
    CSI_LINE_PREFIX,
)
from preprocessor import (
    CSIConfig,
    StreamingPreprocessor,
    MotionState,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("visualizer")


# ---------------------------------------------------------------------------
# Visualizer configuration
# ---------------------------------------------------------------------------
class VizConfig:
    HISTORY          = 200    # packets in heatmap x-axis
    VAR_HISTORY      = 150    # variance samples shown
    RSSI_HISTORY     = 150    # RSSI samples shown
    ANIM_INTERVAL_MS = 100    # redraw interval (~10 fps)
    DRAIN_PER_FRAME  = 15     # max packets consumed per animation frame

    AMP_YMIN         = 0
    AMP_YMAX         = 40

    MOTION_COLOR     = "#e74c3c"    # red
    STATIC_COLOR     = "#2ecc71"    # green

    HEATMAP_CMAP     = "viridis"


# ---------------------------------------------------------------------------
# Reader threads
# ---------------------------------------------------------------------------

def reader_thread_serial(port: str, baud: int,
                         pkt_queue: queue.Queue,
                         stop_event: threading.Event) -> None:
    """
    Background thread: reads serial lines, validates, parses, enqueues.
    If the queue is full, drops the oldest packet to make room.
    """
    log.info("[reader] Opening %s @ %d baud …", port, baud)
    try:
        ser = serial.Serial(port, baud, timeout=1.0)
    except serial.SerialException as exc:
        log.error("[reader] Cannot open port: %s", exc)
        stop_event.set()
        return

    log.info("[reader] Serial open. Streaming …")
    while not stop_event.is_set():
        try:
            raw = ser.readline().decode("utf-8", errors="replace").strip()
        except serial.SerialException as exc:
            log.warning("[reader] Read error: %s", exc)
            time.sleep(0.05)
            continue

        if not raw.startswith(CSI_LINE_PREFIX):
            continue

        valid, _ = validate_csi_line(raw)
        if not valid:
            continue

        pkt = parse_csi_line(raw)
        if pkt is None:
            continue

        # Drop oldest if queue full
        if pkt_queue.full():
            try:
                pkt_queue.get_nowait()
            except queue.Empty:
                pass
        pkt_queue.put_nowait(pkt)

    ser.close()
    log.info("[reader] Serial closed.")


def reader_thread_csv(filepath: str,
                      pkt_queue: queue.Queue,
                      stop_event: threading.Event) -> None:
    """
    CSV replay reader: reads a recorded CSV at simulated 50 Hz.
    Allows testing and demonstration without hardware.
    """
    log.info("[reader] Replaying CSV: %s", filepath)
    df       = pd.read_csv(filepath)
    amp_cols = sorted(
        [c for c in df.columns if c.startswith("amp_")],
        key=lambda c: int(c.split("_")[1]),
    )

    for _, row in df.iterrows():
        if stop_event.is_set():
            break

        amps = row[amp_cols].tolist()
        pkt  = {
            "timestamp_us":    int(row.get("timestamp_us", 0)),
            "rssi":            int(row.get("rssi", -65)),
            "num_subcarriers": len(amps),
            "amplitudes":      amps,
        }

        if pkt_queue.full():
            try:
                pkt_queue.get_nowait()
            except queue.Empty:
                pass
        pkt_queue.put_nowait(pkt)
        time.sleep(1.0 / 50.0)  # 50 Hz replay

    log.info("[reader] CSV replay complete.")
    stop_event.set()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class CSIDashboard:
    """
    Builds and animates the 4-panel matplotlib CSI dashboard.
    """

    def __init__(self, pkt_queue: queue.Queue,
                 stop_event: threading.Event,
                 csi_cfg: CSIConfig = None,
                 vcfg: VizConfig = None):
        self.queue       = pkt_queue
        self.stop        = stop_event
        self.csi_cfg     = csi_cfg or CSIConfig()
        self.vcfg        = vcfg    or VizConfig()
        self.proc        = StreamingPreprocessor(self.csi_cfg)

        # Rolling history buffers
        self._amp_history  = deque(maxlen=self.vcfg.HISTORY)
        self._var_history  = deque(maxlen=self.vcfg.VAR_HISTORY)
        self._rssi_history = deque(maxlen=self.vcfg.RSSI_HISTORY)

        # Current state
        self._motion_state  = MotionState.STATIC
        self._current_amps  = None
        self._n_sc          = None
        self._pkt_count     = 0
        self._t_start       = time.monotonic()

        self._build_figure()

    # ── Figure construction ───────────────────────────────────────────────

    def _build_figure(self):
        matplotlib.rcParams.update({
            "figure.facecolor": "#0d1117",
            "axes.facecolor":   "#161b22",
            "axes.edgecolor":   "#30363d",
            "axes.labelcolor":  "#c9d1d9",
            "axes.grid":        True,
            "grid.color":       "#21262d",
            "grid.linewidth":   0.5,
            "xtick.color":      "#8b949e",
            "ytick.color":      "#8b949e",
            "text.color":       "#c9d1d9",
            "font.family":      "monospace",
        })

        self.fig = plt.figure(figsize=(14, 9), constrained_layout=True)
        self.fig.patch.set_facecolor("#0d1117")
        self.fig.suptitle(
            "ESP32-S3  ·  WiFi CSI Sensing  ·  Real-Time Dashboard",
            fontsize=13, fontweight="bold", color="#58a6ff",
        )

        gs = gridspec.GridSpec(
            3, 2, figure=self.fig,
            height_ratios=[2.0, 1.8, 1.2],
            width_ratios=[3, 1],
            hspace=0.4, wspace=0.18,
        )

        self.ax_amp   = self.fig.add_subplot(gs[0, 0])
        self.ax_state = self.fig.add_subplot(gs[0, 1])
        self.ax_heat  = self.fig.add_subplot(gs[1, :])
        self.ax_var   = self.fig.add_subplot(gs[2, :])

        self._setup_ax_amp()
        self._setup_ax_state()
        self._setup_ax_heat()
        self._setup_ax_var()

    def _setup_ax_amp(self):
        ax = self.ax_amp
        ax.set_title("Subcarrier amplitudes", fontsize=10, color="#8b949e")
        ax.set_xlabel("Subcarrier index", fontsize=9)
        ax.set_ylabel("Amplitude", fontsize=9)
        ax.set_ylim(self.vcfg.AMP_YMIN, self.vcfg.AMP_YMAX)
        self.line_raw,  = ax.plot([], [], color="#3fb950", lw=0.7,
                                  alpha=0.4, label="raw")
        self.line_smth, = ax.plot([], [], color="#58a6ff", lw=1.5,
                                  label="smoothed")
        ax.legend(loc="upper right", fontsize=8,
                  facecolor="#161b22", edgecolor="#30363d",
                  labelcolor="#c9d1d9")

    def _setup_ax_state(self):
        ax = self.ax_state
        ax.set_axis_off()
        ax.set_title("Motion state", fontsize=10, color="#8b949e")

        self.state_box = FancyBboxPatch(
            (0.05, 0.25), 0.90, 0.50,
            boxstyle="round,pad=0.05",
            facecolor=self.vcfg.STATIC_COLOR,
            edgecolor="none",
            transform=ax.transAxes, zorder=2,
        )
        ax.add_patch(self.state_box)

        self.state_text = ax.text(
            0.5, 0.53, MotionState.STATIC,
            ha="center", va="center",
            fontsize=12, fontweight="bold",
            color="white", transform=ax.transAxes, zorder=3,
        )
        self.var_text = ax.text(
            0.5, 0.30, "var: 0.000",
            ha="center", va="center",
            fontsize=9, color="white", alpha=0.85,
            transform=ax.transAxes, zorder=3,
        )
        self.rate_text = ax.text(
            0.5, 0.90, "0 pkt/s",
            ha="center", va="top",
            fontsize=8, color="#8b949e",
            transform=ax.transAxes,
        )
        self.pkt_text = ax.text(
            0.5, 0.08, "pkts: 0",
            ha="center", va="bottom",
            fontsize=8, color="#8b949e",
            transform=ax.transAxes,
        )

    def _setup_ax_heat(self):
        ax = self.ax_heat
        ax.set_title(
            f"Amplitude heatmap  (last {self.vcfg.HISTORY} packets × subcarriers)",
            fontsize=10, color="#8b949e",
        )
        ax.set_xlabel("Time (packets)", fontsize=9)
        ax.set_ylabel("Subcarrier", fontsize=9)
        placeholder = np.zeros((52, self.vcfg.HISTORY))
        self.heatmap = ax.imshow(
            placeholder,
            aspect="auto", origin="lower",
            cmap=self.vcfg.HEATMAP_CMAP,
            vmin=self.vcfg.AMP_YMIN,
            vmax=self.vcfg.AMP_YMAX,
            interpolation="nearest",
        )
        self.fig.colorbar(
            self.heatmap, ax=ax,
            fraction=0.012, pad=0.01,
            label="Amplitude",
        )

    def _setup_ax_var(self):
        ax = self.ax_var
        ax.set_title("Rolling variance (motion indicator) & RSSI", fontsize=10, color="#8b949e")
        ax.set_xlabel("Time (packets)", fontsize=9)
        ax.set_ylabel("Variance", fontsize=9)
        ax.set_ylim(0, max(self.csi_cfg.motion_threshold * 3, 1.5))

        # Threshold lines
        ax.axhline(self.csi_cfg.motion_threshold,
                   color="#e74c3c", lw=1.0, ls="--", alpha=0.7,
                   label=f"motion ({self.csi_cfg.motion_threshold})")
        ax.legend(loc="upper right", fontsize=8,
                  facecolor="#161b22", edgecolor="#30363d",
                  labelcolor="#c9d1d9")

        self.line_var, = ax.plot([], [], color="#e74c3c", lw=1.2)

        # Secondary axis for RSSI
        self.ax_rssi = ax.twinx()
        self.ax_rssi.set_ylabel("RSSI (dBm)", fontsize=9, color="#f39c12")
        self.ax_rssi.tick_params(labelcolor="#f39c12")
        self.ax_rssi.set_ylim(-100, 0)
        self.line_rssi, = self.ax_rssi.plot([], [], color="#f39c12",
                                             lw=0.8, alpha=0.6)

        self._var_fill = None

    # ── Animation frame ───────────────────────────────────────────────────

    def _animate(self, frame: int):
        """Called by FuncAnimation every ANIM_INTERVAL_MS ms."""
        updated = False

        for _ in range(self.vcfg.DRAIN_PER_FRAME):
            try:
                pkt = self.queue.get_nowait()
            except queue.Empty:
                break

            self._pkt_count += 1
            self._rssi_history.append(pkt["rssi"])

            result = self.proc.push(pkt["amplitudes"])
            if result is None:
                continue

            updated = True
            self._current_amps = result.amplitudes
            self._motion_state = result.motion_state
            self._n_sc         = len(result.amplitudes)
            self._amp_history.append(result.amplitudes.copy())
            self._var_history.append(result.variance)

        if not updated:
            return

        # ── Panel 1: amplitude line ──────────────────────────────────────
        if self._current_amps is not None:
            x = np.arange(len(self._current_amps))
            self.line_raw.set_data(x, self._current_amps)
            self.ax_amp.set_xlim(0, len(self._current_amps) - 1)

            if len(self._amp_history) >= self.csi_cfg.var_window:
                smth = np.mean(
                    np.stack(list(self._amp_history)[-self.csi_cfg.var_window:]),
                    axis=0,
                )
                self.line_smth.set_data(x, smth)

        # ── Panel 2: motion state ────────────────────────────────────────
        is_motion = (self._motion_state == MotionState.MOTION)
        color     = self.vcfg.MOTION_COLOR if is_motion else self.vcfg.STATIC_COLOR
        self.state_box.set_facecolor(color)
        self.state_text.set_text(self._motion_state)

        if self._var_history:
            self.var_text.set_text(f"var: {self._var_history[-1]:.3f}")

        elapsed = time.monotonic() - self._t_start
        rate    = self._pkt_count / elapsed if elapsed > 0 else 0
        self.rate_text.set_text(f"{rate:.1f} pkt/s")
        self.pkt_text.set_text(f"pkts: {self._pkt_count}")

        # ── Panel 3: heatmap ─────────────────────────────────────────────
        if len(self._amp_history) > 0 and self._n_sc is not None:
            hist = list(self._amp_history)
            mat  = np.zeros((self._n_sc, self.vcfg.HISTORY), dtype=np.float32)
            n_fill = min(len(hist), self.vcfg.HISTORY)
            for i, row in enumerate(hist[-n_fill:]):
                col = self.vcfg.HISTORY - n_fill + i
                mat[:, col] = row
            self.heatmap.set_data(mat)

        # ── Panel 4: variance + RSSI ─────────────────────────────────────
        if len(self._var_history) > 0:
            var_arr = np.array(list(self._var_history), dtype=np.float32)
            x_var   = np.arange(len(var_arr))
            self.line_var.set_data(x_var, var_arr)
            self.ax_var.set_xlim(0, max(len(var_arr) - 1, self.vcfg.VAR_HISTORY))
            cur_max = max(float(np.max(var_arr)) * 1.2, self.csi_cfg.motion_threshold * 2)
            self.ax_var.set_ylim(0, cur_max)

            if self._var_fill is not None:
                self._var_fill.remove()
            self._var_fill = self.ax_var.fill_between(
                x_var, 0, var_arr, color="#e74c3c", alpha=0.15,
            )

        if len(self._rssi_history) > 0:
            rssi_arr = np.array(list(self._rssi_history), dtype=np.float32)
            # Align RSSI x-axis with variance x-axis length
            x_rssi = np.linspace(0, max(len(rssi_arr) - 1, 1), len(rssi_arr))
            self.line_rssi.set_data(x_rssi, rssi_arr)

    # ── Launch ────────────────────────────────────────────────────────────

    def run(self):
        self._anim = FuncAnimation(
            self.fig,
            self._animate,
            interval=self.vcfg.ANIM_INTERVAL_MS,
            cache_frame_data=False,
            blit=False,
        )
        plt.show()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Real-time CSI visualizer for ESP32-S3",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--port",     default="/dev/ttyACM0")
    p.add_argument("--baud",     default=115200, type=int)
    p.add_argument("--csv",      default=None,
                   help="Replay a recorded CSV file instead of live serial")
    p.add_argument("--motion-threshold",
                   type=float, default=0.5,
                   help="Variance threshold for 'Motion detected'")
    p.add_argument("--presence-threshold",
                   type=float, default=0.1)
    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = build_parser().parse_args()

    csi_cfg = CSIConfig()
    csi_cfg.motion_threshold   = args.motion_threshold
    csi_cfg.presence_threshold = args.presence_threshold

    pkt_queue  = queue.Queue(maxsize=500)
    stop_event = threading.Event()

    if args.csv:
        log.info("Replay mode: %s", args.csv)
        reader_fn   = reader_thread_csv
        reader_args = (args.csv, pkt_queue, stop_event)
    else:
        log.info("Live mode: %s @ %d baud", args.port, args.baud)
        reader_fn   = reader_thread_serial
        reader_args = (args.port, args.baud, pkt_queue, stop_event)

    reader = threading.Thread(target=reader_fn, args=reader_args, daemon=True)
    reader.start()

    try:
        dashboard = CSIDashboard(pkt_queue, stop_event, csi_cfg)
        dashboard.run()
    except KeyboardInterrupt:
        log.info("Interrupted.")
    finally:
        stop_event.set()
        reader.join(timeout=2.0)
        log.info("Shutdown complete.")
