import logging
import os
from typing import Dict, Optional, Tuple

import lalpulsar
import matplotlip as plt
import numpy as np

logger = logging.getLogger(__name__)


def get_sft_as_arrays(
    sftfilepattern: str,
    fMin: Optional[float] = None,
    fMax: Optional[float] = None,
    constraints: Optional[lalpulsar.SFTConstraints] = None,
) -> Tuple[np.ndarray, Dict, Dict]:
    """
    Read binary SFT files into NumPy arrays.

    Parameters
    ----------
    sftfilepattern:
        Pattern to match SFTs using wildcards (`*?`) and ranges [0-9];
        multiple patterns can be given separated by colons.
    fMin, fMax:
        Restrict frequency range to `[fMin, fMax]`.
        If None, retrieve the full frequency range.
    constraints:
        Constrains to be fed into XLALSFTdataFind to specify detector,
        GPS time range or timestamps to be retrieved.

    Returns
    ----------
    freqs: np.ndarray
        The frequency bins in each SFT. These will be the same for each SFT,
        so only a single 1D array is returned.
    times: Dict
        The SFT start times as a dictionary of 1D arrays, one for each detector.
        Keys correspond to the official detector names as returned by
        lalpulsar.ListIFOsInCatalog.
    data: Dict
        A dictionary of 2D arrays of the complex Fourier amplitudes of the SFT data
        for each detector in each frequency bin at each timestamp.
        Keys correspond to the official detector names as returned by
        lalpulsar.ListIFOsInCatalog.
    """
    constraints = constraints or lalpulsar.SFTConstraints()
    if fMin is None and fMax is None:
        fMin = fMax = -1
    elif fMin is None or fMax is None:
        raise ValueError("Need either none or both of fMin, fMax.")

    sft_catalog = lalpulsar.SFTdataFind(sftfilepattern, constraints)
    ifo_labels = lalpulsar.ListIFOsInCatalog(sft_catalog)

    logger.info(
        f"Loading {sft_catalog.length} SFTs from {', '.join(ifo_labels.data)}..."
    )
    multi_sfts = lalpulsar.LoadMultiSFTs(sft_catalog, fMin, fMax)
    logger.debug("done!")

    times = {}
    amplitudes = {}

    old_frequencies = None
    for ind, ifo in enumerate(ifo_labels.data):
        sfts = multi_sfts.data[ind]

        times[ifo] = np.array([sft.epoch.gpsSeconds for sft in sfts.data])
        amplitudes[ifo] = np.array([sft.data.data for sft in sfts.data]).T

        nbins, nsfts = amplitudes[ifo].shape

        logger.debug(f"{nsfts} retrieved from {ifo}.")

        f0 = sfts.data[0].f0
        df = sfts.data[0].deltaF
        frequencies = np.linspace(f0, f0 + (nbins - 1) * df, nbins)

        if (old_frequencies is not None) and not np.allclose(
            frequencies, old_frequencies
        ):
            raise ValueError(
                f"Frequencies don't match between {ifo_labels.data[ind - 1]} and {ifo}"
            )
        old_frequencies = frequencies

    return frequencies, times, amplitudes


def get_commandline_from_SFTDescriptor(descriptor):
    """Extract a commandline from the 'comment' entry of a SFT descriptor.

    Most LALSuite SFT creation tools save their commandline into that entry,
    so we can extract it and reuse it to reproduce that data.

    Since lalapps 9.0.0 / lalpulsar 5.0.0
    the relevant executables have been moved to lalpulsar,
    but we allow for lalapps backwards compatibility here,

    Parameters
    ----------
    descriptor: SFTDescriptor
        Element of a `lalpulsar.SFTCatalog` structure.

    Returns
    -------
    cmd: str
        A lalapps/lalpulsar commandline string,
        or an empty string if no match in comment.
    """
    comment = getattr(descriptor, "comment", None)
    if comment is None:
        return ""
    comment_lines = comment.split("\n")
    # get the first line with the right substring
    # (iterate until it's found)
    return next(
        (line for line in comment_lines if "lalpulsar" in line or "lalapps" in line), ""
    )


def get_official_sft_filename(
    IFO,
    numSFTs,
    Tsft,
    tstart,
    duration,
    label=None,
    window_type=None,
    window_param=None,
):
    """Wrapper to predict the canonical lalpulsar names for SFT files.

    Parameters
    ----------
    IFO: str
        Two-char detector name, e.g. `H1`.
    numSFTs: int
        numSFTs	number of SFTs in SFT-file
    Tsft: int
        time-baseline in (integer) seconds
    tstart: int
        GPS seconds of first SFT start time
    duration: int
        total time-spanned by all SFTs in seconds
    label: str or None
        optional 'Misc' entry in the SFT 'D' field
    window_type: str or None
        window function applied to SFTs
    window_param: float or None
        additional parameter for some window functions

    Returns
    -------
    filename: str
        The canonical SFT file name for the input parameters.
    """
    spec = lalpulsar.SFTFilenameSpec()
    lalpulsar.FillSFTFilenameSpecStrings(
        spec=spec,
        path=None,
        extn=None,
        detector=IFO,
        window_type=window_type,
        privMisc=label,
        pubObsKind=None,
        pubChannel=None,
    )
    spec.window_param = window_param or 0
    spec.numSFTs = numSFTs
    spec.SFTtimebase = Tsft
    spec.gpsStart = tstart
    # possible gotcha: duration may be different if nanoseconds of sft-epochs are non-zero


def plot_real_imag_spectrograms(
    self,
    sftfilepattern: str,
    outdir: str,
    label: str,
    quantity: Optional[str] = "norm_Power",
    fMin: Optional[float] = None,
    fMax: Optional[float] = None,
    constraints: Optional[lalpulsar.SFTConstraints] = None,
    **kwargs,
):
    """
    Compute spectrograms of a set of SFTs.
    This is useful to produce visualizations of the Doppler modulation of a CW signal.

    Parameters
    ----------
    sftfilepattern:
        Pattern to match SFTs using wildcards (`*?`) and ranges [0-9];
        multiple patterns can be given separated by colons.
    outdir:
        Output folder.
    label:
        Output filename.
    quantity:
        Magnitude to be plotted.
        It can be "norm_Power" for normalized power, "Re" for the real part of
        the SFTs, and "Im" for the imaginary part of the SFTs.
    fMin, fMax:
        Restrict frequency range to `[fMin, fMax]`.
        If None, retrieve the full frequency range.
    constraints:
        Constrains to be fed into XLALSFTdataFind to specify detector,
        GPS time range or timestamps to be retrieved.
    kwarg: dict
        Other kwargs.

    Returns
    -------
    ax: matplotlib.axes._subplots_AxesSubplot
        The axes object containing the plot.
    """

    outpath = os.path.join(outdir, label)
    logger = logging.set_up_logger(label=label, outdir=outpath)

    logger.info("Loading SFT data")
    frequency, timestamps, fourier_data = get_sft_as_arrays(
        sftfilepattern, fMin, fMax, constraints
    )

    plotfile = os.path.join(outdir, label + ".png")
    logger.info(f"Plotting to file: {plotfile}")

    plt.rcParams["axes.grid"] = False  # turn off the gridlines
    fig, ax = plt.subplots(figsize=(0.8 * 16, 0.8 * 9))
    ax.set(xlabel="Time [days]", ylabel="Frequency [Hz]")

    time_in_days = (timestamps - timestamps[0]) / 86400

    if quantity == "norm_Power":
        logger.info("Computing normalized power")
        sft_power = fourier_data.real**2 + fourier_data.imag**2
        normalized_power = sft_power
        # (2 * sft_power / (data_parameters["Tsft"] * data_parameters["sqrtSX"] ** 2)
        c = ax.pcolormesh(
            time_in_days,
            frequency,
            normalized_power,
            cmap="inferno_r",
            shading="nearest",
        )
        fig.colorbar(c, label="Normalized Power")

    elif quantity == "Re":
        c = ax.pcolormesh(
            time_in_days,
            frequency,
            fourier_data.real,
            cmap="inferno_r",
            shading="nearest",
        )
        ax.set_title("SFT Real part")
        fig.colorbar(c, label="Fourier amplitude")

    elif quantity == "Im":
        c = ax.pcolormesh(
            time_in_days,
            frequency,
            fourier_data.imag,
            cmap="inferno_r",
            shading="nearest",
        )
        ax.set_title("SFT Imaginary part")
        fig.colorbar(c, label="Fourier amplitude")

    else:
        raise ValueError(
            "String `quantity` not accepted. Please, introduce a valid string"
        )

    plt.tight_layout()
    fig.savefig(plotfile)

    return ax
