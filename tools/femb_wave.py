#!/usr/bin/env python3
"""Decode FEMB QC raw .bin files (WIBEth spy-buffer pickles) and plot waveforms.

Raw data lives under the QC raw root (see docs/agents/diagnosis.md), in run
directories parallel to the report mirror:
    <raw-root>/Time_<YYYY>_<MM>/<run-name>/QC/<TEST>/QC_*_t<N>.bin

Each .bin is a Python pickle: a dict keyed by config name (e.g.
"RMS_SE_900mVBL_14_0mVfC_2_0us_0x00.bin"); value[0] is a list of acquisition
events, each ([buf0..buf7], buf_end_addr, trigger_rec_ticks, trig_cmd) where
bufs[femb*2 + cd] are 256 KiB WIBEth spy-buffer dumps (2 COLDATA streams of
64 channels per FEMB slot).

Frame layout (899 x 64-bit LE words; from DUNE-DAQ WIBEthFrame via
sgaobnl/BNL_CE_WIB_SW_QC Analysis/decode/dunedaq_decode.py):
    word 0     : 64-bit WIB timestamp (increments 0x800 per frame)
    word 1     : colddata timestamps (two 15-bit fields, equal when synced)
    word 2     : 0
    words 3-898: adc_words[64 samples][14 words]; channel c of a sample
                 occupies bits c*14 .. c*14+13 of the 14-word LE bitstream

Usage examples:
    # list config keys in a raw file
    python3 tools/femb_wave.py --bin <path>/QC_femb_rms_t5.bin --list-keys

    # scan all configs/events for baseline jumps on one channel
    python3 tools/femb_wave.py --bin <...>.bin --femb 0 --scan 16

    # plot a waveform (channel 16 + neighbor 15); --event takes a list (one column each)
    python3 tools/femb_wave.py --bin <...>.bin --femb 0 --ch 16,15 \
        --key RMS_SELC_200mVBL_14_0mVfC_2_0us_5nA --event 6 --out analysis/waveforms

    # neighbour comparison with an amplitude histogram column, named output
    python3 tools/femb_wave.py --bin <...>.bin --femb 0 --ch 15,16,17 --hist \
        --key RMS_SELC_200mVBL_14_0mVfC_2_0us_5nA --event 6 \
        --out analysis/waveforms/<date>_FEMB-<serial> --out-name wave_ch16.png
"""
import argparse
import os
import pickle
import sys

import numpy as np

PKT_LEN = 899
N_SAMPLES = 64
N_CH = 64
TICK_US = 0.512


def decode_stream(buf):
    """Decode one 64-channel spy-buffer stream -> (nsamples, 64) uint16,
    frames sorted by timestamp (ring buffer unwrapped)."""
    words = np.frombuffer(bytes(buf), dtype="<u8")
    n = len(words)
    idx = np.arange(n - PKT_LEN)
    cond = (
        (words[idx + PKT_LEN] - words[idx] == 0x800)
        & ((words[idx + 1] & 0x7FFF) == ((words[idx + 1] >> 16) & 0x7FFF))
        & (words[idx + 2] == 0)
    )
    starts = idx[cond]
    keep = []
    last = -PKT_LEN
    for s in starts:
        if s >= last + PKT_LEN:
            keep.append(s)
            last = s
    starts = np.array(keep)
    if len(starts) == 0:
        raise ValueError("no WIBEth frames found in buffer")
    ts = words[starts]
    starts = starts[np.argsort(ts)]

    frames = np.stack([words[s + 3 : s + 3 + N_SAMPLES * 14] for s in starts])
    frames = frames.reshape(len(starts), N_SAMPLES, 14)

    adcs = np.zeros((len(starts), N_SAMPLES, N_CH), dtype=np.uint16)
    for c in range(N_CH):
        nb = 14 * c
        wi, fb = nb // 64, nb % 64
        v = frames[:, :, wi] >> np.uint64(fb)
        if fb > 50:  # 14-bit field spans into the next word
            v = v | (frames[:, :, wi + 1] << np.uint64(64 - fb))
        adcs[:, :, c] = (v & np.uint64(0x3FFF)).astype(np.uint16)
    return adcs.reshape(-1, N_CH)


def decode_femb(bufs, femb):
    """Decode one FEMB slot (two streams) -> (nsamples, 128) uint16."""
    a0 = decode_stream(bufs[femb * 2])       # channels 0-63
    a1 = decode_stream(bufs[femb * 2 + 1])   # channels 64-127
    ns = min(len(a0), len(a1))
    return np.hstack([a0[:ns], a1[:ns]])


def frame_means(w):
    """Per-frame (64-sample) baseline means of one channel waveform."""
    n = len(w) // N_SAMPLES * N_SAMPLES
    return w[:n].astype(float).reshape(-1, N_SAMPLES).mean(axis=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bin", required=True, help="path to a QC raw .bin pickle")
    ap.add_argument("--list-keys", action="store_true", help="list config keys and exit")
    ap.add_argument("--femb", type=int, default=0, help="FEMB slot (S0=0, S1=1, ...)")
    ap.add_argument("--scan", type=int, metavar="CH",
                    help="scan all configs/events for baseline jumps on channel CH")
    ap.add_argument("--ch", help="comma-separated channels to plot (0-127)")
    ap.add_argument("--key", help="config key to plot (substring match allowed)")
    ap.add_argument("--event", default="0",
                    help="event index, or comma-separated indices (one column each)")
    ap.add_argument("--hist", action="store_true",
                    help="add an ADC amplitude histogram column (one per channel)")
    ap.add_argument("--out", default=".", help="output directory for PNGs")
    ap.add_argument("--out-name", help="output filename (default: derived from ch/key/event)")
    args = ap.parse_args()

    if not os.path.exists(args.bin) and os.environ.get("FEMB_RAW_DIR"):
        candidate = os.path.join(os.environ["FEMB_RAW_DIR"], args.bin)
        if os.path.exists(candidate):
            args.bin = candidate

    with open(args.bin, "rb") as f:
        data = pickle.load(f)
    keys = [k for k in data if isinstance(data[k], list) and data[k] and isinstance(data[k][0], list)]

    if args.list_keys:
        for k in keys:
            print(k, f"({len(data[k][0])} events)")
        return

    if args.scan is not None:
        ch = args.scan
        rows = []
        for k in keys:
            for iev, ev in enumerate(data[k][0]):
                wf = decode_femb(ev[0], args.femb)
                fm = frame_means(wf[:, ch])
                rows.append((float(np.abs(np.diff(fm)).max()), float(fm.max() - fm.min()),
                             float(wf[:, ch].std()), k, iev))
        rows.sort(reverse=True)
        print(f"ch {ch} baseline-jump scan (femb {args.femb}); top 15 by max frame-to-frame step:")
        print(f"{'step':>7} {'spread':>7} {'rms':>6}  config / event")
        for r in rows[:15]:
            print(f"{r[0]:7.1f} {r[1]:7.1f} {r[2]:6.2f}  {r[3]}  ev{r[4]}")
        return

    if not args.ch:
        ap.error("--ch is required unless --list-keys or --scan is used")
    chans = [int(c) for c in args.ch.split(",")]
    matches = [k for k in keys if args.key and args.key in k] if args.key else keys[:1]
    if not matches:
        sys.exit(f"no config key matches {args.key!r}; use --list-keys")
    key = matches[0]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    events = [int(e) for e in args.event.split(",")]
    wfs = [decode_femb(data[key][0][iev][0], args.femb) for iev in events]

    ncols = len(events) + (1 if args.hist else 0)
    fig, axes = plt.subplots(len(chans), ncols,
                             figsize=(7.5 * len(events) + (4 if args.hist else 0),
                                      2.8 * len(chans)), squeeze=False)
    for row, ch in enumerate(chans):
        for col, (iev, wf) in enumerate(zip(events, wfs)):
            w = wf[:, ch]
            fm = frame_means(w)
            ax = axes[row, col]
            ax.plot(w, lw=0.6)
            ax.plot(np.arange(len(fm)) * N_SAMPLES + N_SAMPLES / 2, fm, lw=1.4, color="crimson")
            ax.set_ylabel(f"ch {ch}\nADC")
            ax.set_xlabel(f"sample ({TICK_US} us/tick)")
            ax.set_title(f"event {iev}", fontsize=10)
            print(f"ch {ch} ev{iev}: ped={w.mean():.1f} rms={w.std():.2f} "
                  f"frame-mean spread={fm.max() - fm.min():.1f} "
                  f"max step={np.abs(np.diff(fm)).max():.1f}")
        if args.hist:
            ax = axes[row, -1]
            for iev, wf in zip(events, wfs):
                ax.hist(wf[:, ch], bins=80, histtype="step", label=f"ev{iev}")
            ax.set_xlabel("ADC")
            ax.set_ylabel("samples")
            ax.set_title(f"ch {ch} amplitude", fontsize=10)
            if len(events) > 1:
                ax.legend(fontsize=8)
    fig.suptitle(f"femb {args.femb}  {key.replace('.bin', '')}", fontsize=11)
    os.makedirs(args.out, exist_ok=True)
    default_name = (f"wave_femb{args.femb}_ch{'-'.join(map(str, chans))}_"
                    f"{key.replace('.bin', '')}_ev{'-'.join(map(str, events))}.png")
    fname = os.path.join(args.out, args.out_name or default_name)
    plt.tight_layout()
    plt.savefig(fname, dpi=110)
    print("saved", fname)


if __name__ == "__main__":
    main()
