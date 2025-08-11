from __future__ import annotations
import math
from typing import Dict, Any

from .base import ConverterDesign
from .core_utils import (
    parse_num,
    core_ss0_min,
    primary_turns,
    ccm_check,
)

class ForwardDesign(ConverterDesign):
    """Simple forward converter calculations."""

    @staticmethod
    def normalize_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
        def p(x):
            try:
                return parse_num(x)
            except Exception:
                return x
        if "input" in cfg:
            for k in ["vin_min", "vin_max", "fsw", "duty_max"]:
                if k in cfg["input"]:
                    cfg["input"][k] = p(cfg["input"][k])
        if "outputs" in cfg:
            for o in cfg["outputs"]:
                for k in ["v", "i", "ripple_v"]:
                    if k in o:
                        o[k] = p(o[k])
        if "core" in cfg:
            for k in ["ae_mm2", "bmax_T"]:
                if k in cfg["core"]:
                    cfg["core"][k] = p(cfg["core"][k])
        return cfg

    def run_calculation(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.normalize_cfg(cfg)
        inp = cfg.get("input", {})
        core = cfg.get("core", {})
        outs = cfg.get("outputs", [])
        if not outs:
            raise ValueError("At least one output required")
        out = outs[0]

        vin_min = inp.get("vin_min")
        vin_max = inp.get("vin_max")
        fsw = inp.get("fsw")
        d_max = inp.get("duty_max", 0.45)
        vout = out.get("v")
        iout = out.get("i")
        delta_i = out.get("delta_i") or 0.4 * iout

        bmax = core.get("bmax_T")
        ae = core.get("ae_mm2") * 1e-6  # mm^2 → m^2
        pout = vout * iout

        if vin_min is None or vin_max is None or fsw is None:
            raise ValueError("Input voltages and frequency are required")

        n_ps = (vin_min * d_max) / vout
        w1 = primary_turns(vin_min, d_max, bmax, ae, fsw)
        w2 = math.ceil(w1 / n_ps)

        vds = vin_max * 2  # worst case with 1:1 reset
        l_min = (vout * (1 - d_max)) / (delta_i * fsw * 2)
        mode = "CCM" if ccm_check(l_min, iout, delta_i, fsw) else "DCM"
        ss0 = core_ss0_min(pout, fsw, bmax)

        return {
            "turns_ratio": round(n_ps, 3),
            "primary_turns": w1,
            "secondary_turns": w2,
            "vds_max": round(vds, 1),
            "l_out_min_uH": round(l_min * 1e6, 2),
            "output_current_mode": mode,
            "SS0_min_cm4": round(ss0, 3),
        }
