from __future__ import annotations
import math
from typing import Dict, Any

from .base import ConverterDesign
from .core_utils import parse_num, core_ss0_min, primary_turns

class PushPullDesign(ConverterDesign):
    """Two-transistor push-pull converter."""

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
                for k in ["v", "i"]:
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

        bmax = core.get("bmax_T")
        ae = core.get("ae_mm2") * 1e-6
        pout = vout * iout

        n_ps = (vin_min * d_max) / vout
        w_half = primary_turns(vin_min, d_max, bmax, ae, fsw)
        w1_total = w_half * 2
        w2_total = math.ceil(w_half / n_ps) * 2
        vds = 2 * vin_max
        ss0 = core_ss0_min(pout, fsw, bmax)

        return {
            "turns_ratio": round(n_ps, 3),
            "primary_turns_total": w1_total,
            "secondary_turns_total": w2_total,
            "vds_max": vds,
            "SS0_min_cm4": round(ss0, 3),
        }
