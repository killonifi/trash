
"""flyback_core.py
Core calculations for multi-output flyback converter in discontinuous‑conduction mode (DCM).

This implementation is not aimed at manufacturing‑grade precision; it is a
didactic reference model that shows **how** the key parameters interact.
Feel free to replace the formulas with your own company‑proven models.

Notation is consistent with the README.
All values are SI (base) unless explicitly noted.
"""

import math
from typing import List, Dict, Any


class FlybackResult(dict):
    """Dictionary subclass so attribute access works: res.Ipk etc."""
    def __getattr__(self, item):
        return self[item]


class FlybackCore:
    """Single‑shot calculator for a multi‑output flyback.

    The model assumes:
    * Discontinuous conduction mode (DCM)
    * Ideal diodes / synchronous rectifiers (efficiency lumped into `eta`)
    * Single primary winding, *n* secondary windings on the **same transformer**
    * Peak‑current mode control ignored; switching frequency is fixed.

    The design target is to pick a duty ratio *D* that minimises **Ipk**
    ("min‑ipk" criterion).  The algorithm sweeps a discrete set of D in
    [0.2 … 0.5] and chooses the best.  If you want a different criterion,
    plug your own cost function into `_choose_best()`.

    After *D* and *Ipk* are known, the necessary primary inductance **L_p**
    is back‑calculated from energy balance per cycle.

    RCD snubber is sized for a given leakage inductance if present.

    Parameters
    ----------
    Vin_min : float
        Minimum input voltage (V).
    Vin_max : float
        Maximum input voltage (V).  Not used in the present model except to
        report in the results.
    Vouts : list[float]
        Output voltages, one per secondary winding (V).
    Iouts : list[float]
        DC load currents matching Vouts (A).
    fsw : float
        Switching frequency (Hz).  Default 100 kHz.
    eta : float
        Overall assumed efficiency (0 < eta ≤ 1).  Default 0.9.
    k_rcd : float | None
        Ratio V_clamp / Vin_max used for the dissipative RCD snubber sizing.
        If None, snubber is not evaluated.

    Returns
    -------
    FlybackResult
        Dict‑like object with all intermediates and a waveform dictionary.

    """

    def __init__(
        self,
        Vin_min: float,
        Vin_max: float,
        Vouts: List[float],
        Iouts: List[float],
        fsw: float = 100e3,
        eta: float = 0.9,
        k_rcd: float | None = 3.0,
    ):
        if len(Vouts) != len(Iouts):
            raise ValueError("Vouts and Iouts must be same length")
        if any(v <= 0 for v in Vouts):
            raise ValueError("All Vouts must be positive")
        if any(i <= 0 for i in Iouts):
            raise ValueError("All Iouts must be positive")
        if not (0 < eta <= 1):
            raise ValueError("eta must be 0 < eta ≤ 1")

        self.Vin_min = Vin_min
        self.Vin_max = Vin_max
        self.Vouts = Vouts
        self.Iouts = Iouts
        self.fsw = fsw
        self.eta = eta
        self.k_rcd = k_rcd

        self._calc()

    # --------------------------------------------------------------------- #
    # Private helpers
    # --------------------------------------------------------------------- #

    def _calc(self) -> None:
        Pout = sum(v * i for v, i in zip(self.Vouts, self.Iouts))  # W

        # Candidate duty‑cycles to try (20 % … 50 %)
        candidates = [0.20 + 0.02 * n for n in range(16)]  # 0.20, 0.22, …, 0.50
        D_best, Ipk_best = self._choose_best(candidates, Pout)

        # Energy per cycle that must be stored in Lp
        E_cycle = Pout / (self.fsw * self.eta)  # J

        # Primary inductance needed
        Lp = 2 * E_cycle / (Ipk_best ** 2)  # H

        # Primary current waveform (triangular, 0 → Ipk in time D*Tsw)
        T = 1.0 / self.fsw
        t_primary = [0.0, D_best * T, T]  # s
        i_primary = [0.0, Ipk_best, 0.0]  # A

        # Secondary waveforms scaled by volt‑second balance
        # For ideal flyback in DCM: N_s/N_p = V_out / (Vin_min * D_best / (1 - D_best))
        N_ratio = [
            vo / (self.Vin_min * D_best / (1 - D_best)) for vo in self.Vouts
        ]

        # Each secondary conducts after primary demagnetises; assume same
        # triangular shape scaled by turns ratio and load current.
        # Secondary peak current is primary Ipk * Np/Ns
        isec_peak = [Ipk_best / n for n in N_ratio]

        waveforms = {"primary": (t_primary, i_primary)}
        for k, (n, ipk_sec) in enumerate(zip(N_ratio, isec_peak)):
            t_sec = [D_best * T, T, T]  # start at demag, then linear down to 0 at T
            i_sec = [ipk_sec, 0.0, 0.0]
            waveforms[f"secondary_{k+1}"] = (t_sec, i_sec)

        res = FlybackResult(
            Vin_min=self.Vin_min,
            Vin_max=self.Vin_max,
            fsw=self.fsw,
            D=D_best,
            Ipk=Ipk_best,
            Lp=Lp,
            Pout=Pout,
            waveforms=waveforms,
        )

        # RCD snubber if requested (very rough, based on k_rcd)
        if self.k_rcd:
            Llk = 0.02 * Lp  # assume 2 % leakage, purely illustrative
            E_leak = 0.5 * Llk * Ipk_best ** 2
            V_clamp = self.k_rcd * self.Vin_max
            Csnub = E_leak / (0.5 * V_clamp ** 2)
            Rsnub = 1.0 / (2 * math.pi * self.fsw * Csnub)  # critically damped RC
            res.update(
                {
                    "Llk": Llk,
                    "E_leak": E_leak,
                    "V_clamp": V_clamp,
                    "Csnub": Csnub,
                    "Rsnub": Rsnub,
                }
            )

        self.result = res

    # ------------------------------------------------------------------ #
    def _choose_best(self, D_list, Pout):
        """Return (D, Ipk) with minimal Ipk."""
        best = None
        best_Ipk = float("inf")
        for D in D_list:
            if not (0 < D < 0.6):
                continue
            Ipk = 2 * Pout / (self.Vin_min * D)  # A
            if Ipk < best_Ipk:
                best_Ipk = Ipk
                best = D
        return best, best_Ipk

    # ------------------------------------------------------------------ #
    def as_dict(self) -> Dict[str, Any]:
        return dict(self.result)

    # ------------------------------------------------------------------ #
    # Convenience to allow: core = FlybackCore(...); res = core()
    def __call__(self):
        return self.result
