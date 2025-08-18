
from __future__ import annotations
from typing import Dict, Any
from .base import ConverterDesign
from .core_utils import parse_num, estimate_switch_currents_boost, recommend_mosfets, mosfet_loss_estimate

class BuckBoostDesign(ConverterDesign):
    @staticmethod
    def normalize_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
        p = lambda x: parse_num(x); inp = cfg.get("input", {}); out = (cfg.get("outputs") or [{}])[0]
        return {
            "vin_min": p(inp.get("vin_min")), "vin_max": p(inp.get("vin_max")), "fsw": p(inp.get("fsw")),
            "eff": p(inp.get("eff") or 0.92), "cin_vrip": p(inp.get("cin_vrip") or 0.02*(p(inp.get("vin_min")) or 1)),
            "vout": p(out.get("v")), "iout": p(out.get("i")), "ripple_v": p(out.get("ripple_v") or 0.01*(p(out.get("v")) or 1)),
            "delta_i": p(out.get("delta_i") or 0.3*(p(out.get("i")) or 1)),
        }
    def run_calculation(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        vin, vout, fsw, iout = cfg["vin_min"], cfg["vout"], cfg["fsw"], cfg["iout"]
        d = abs(vout) / max(1e-9, abs(vout) + vin); delta_i = cfg["delta_i"]
        L = (vin * d) / (delta_i * fsw); C = (iout * (1 - d)) / (cfg["ripple_v"] * fsw)
        i_in = (abs(vout) * iout) / (cfg["eff"] * vin); Cin = i_in * d / (cfg["cin_vrip"] * fsw)
        v_switch = abs(vout) + vin
        i_rms, i_pk = estimate_switch_currents_boost(vin, abs(vout), iout, d, delta_i, cfg["eff"])
        mosfets = recommend_mosfets(v_switch, i_rms, i_pk, fsw)
        losses = mosfet_loss_estimate(v_switch, i_rms, i_pk, fsw, {'rds_on_mohm': 15, 'tr_ns': 15, 'tf_ns': 15, 'qg_nC': 35, 'vgate_V': 10})
        return {
            "duty": round(d, 4), "l_min_H": L, "l_min_uH": round(L*1e6, 2),
            "c_out_min_F": C, "c_out_min_uF": round(C*1e6, 2), "cin_min_F": Cin, "cin_min_uF": round(Cin*1e6, 2),
            "vds_max_V": round(v_switch, 2), "diode_vrrm_V": round(abs(vout), 2), "polarity": "inverting",
            "losses_W": losses, "recommendations": {"mosfets": mosfets},
        }
