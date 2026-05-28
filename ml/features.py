import numpy as np
from scipy.fft import fft

WINDOW_SIZE = 30
FIXED_SUBCARRIERS = 52


def fix_shape(window):
    """
    Force every CSI window to exactly FIXED_SUBCARRIERS.
    """

    fixed = []

    for row in window:

        row = np.array(row)

        if len(row) > FIXED_SUBCARRIERS:
            row = row[:FIXED_SUBCARRIERS]

        elif len(row) < FIXED_SUBCARRIERS:

            row = np.pad(
                row,
                (0, FIXED_SUBCARRIERS - len(row)),
                mode="constant"
            )

        fixed.append(row)

    return np.array(fixed)


def extract_features(window):

    window = fix_shape(window)

    feats = []

    # Mean
    feats.extend(np.mean(window, axis=0))

    # Std
    feats.extend(np.std(window, axis=0))

    # Variance
    feats.extend(np.var(window, axis=0))

    # Motion energy
    diff = np.diff(window, axis=0)
    feats.extend(np.mean(np.abs(diff), axis=0))

    # FFT energy
    fft_vals = np.abs(fft(window, axis=0))
    feats.extend(np.mean(fft_vals, axis=0))

    return np.array(feats, dtype=np.float32)
