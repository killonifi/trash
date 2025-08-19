
from __future__ import annotations
from typing import Dict, Any
from .base import ConverterDesign
from .core_utils import parse_num, cout_from_tri_ripple, estimate_switch_currents_buck, recommend_mosfets, mosfet_loss_estimate

class BuckDesign(ConverterDesign):
    @staticmethod
    def normalize_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
        p = lambda x: parse_num(x); inp = cfg.get("input", {}); out = (cfg.get("outputs") or [{}])[0]
        return {
            "vin_min": p(inp.get("vin_min")), "vin_max": p(inp.get("vin_max")), "fsw": p(inp.get("fsw")),
            "eff": p(inp.get("eff") or 0.95), "cin_vrip": p(inp.get("cin_vrip") or 0.02*(p(inp.get("vin_min")) or 1)),
            "vout": p(out.get("v")), "iout": p(out.get("i")), "ripple_v": p(out.get("ripple_v") or 0.01*(p(out.get("v")) or 1)),
            "delta_i": p(out.get("delta_i") or 0.3*(p(out.get("i")) or 1)),
        }
    def run_calculation(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        vin, fsw, vout, iout = cfg["vin_min"], cfg["fsw"], cfg["vout"], cfg["iout"]
        d = vout / max(1e-9, vin); delta_i = cfg["delta_i"]
        L = (vout * (1 - d)) / (delta_i * fsw)
        C = cout_from_tri_ripple(delta_i, cfg["ripple_v"], fsw, pulses_per_period=1)
        i_in = (vout * iout) / (cfg["eff"] * vin); Cin = i_in * d / (cfg["cin_vrip"] * fsw)
        vds = vin
        i_rms, i_pk = estimate_switch_currents_buck(iout, d, delta_i); mosfets = recommend_mosfets(vds, i_rms, i_pk, fsw)
        losses = mosfet_loss_estimate(vds, i_rms, i_pk, fsw, {'rds_on_mohm': 10, 'tr_ns': 10, 'tf_ns': 10, 'qg_nC': 20, 'vgate_V': 5})
        return {
            "duty": round(d, 4), "l_out_min_H": L, "l_out_min_uH": round(L*1e6, 2),
            "c_out_min_F": C, "c_out_min_uF": round(C*1e6, 2), "cin_min_F": Cin, "cin_min_uF": round(Cin*1e6, 2),
            "vds_max_V": round(vds, 2), "losses_W": losses, "recommendations": {"mosfets": mosfets},
        }
