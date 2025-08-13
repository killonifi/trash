
from __future__ import annotations
from typing import Dict, Any
from .base import ConverterDesign
from .core_utils import parse_num, estimate_switch_currents_boost, recommend_mosfets, mosfet_loss_estimate

class CukDesign(ConverterDesign):
    @staticmethod
    def normalize_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
        p = lambda x: parse_num(x); inp = cfg.get("input", {}); out = (cfg.get("outputs") or [{}])[0]
        return {
            "vin_min": p(inp.get("vin_min")), "vin_max": p(inp.get("vin_max")), "fsw": p(inp.get("fsw")),
            "eff": p(inp.get("eff") or 0.9), "cin_vrip": p(inp.get("cin_vrip") or 0.02*(p(inp.get("vin_min")) or 1)),
            "vout": p(out.get("v")), "iout": p(out.get("i")), "ripple_v": p(out.get("ripple_v") or 0.01*(p(out.get("v")) or 1)),
            "delta_i_in": p(out.get("delta_i_in") or 0.2*(p(out.get("i")) or 1)), "delta_i_out": p(out.get("delta_i_out") or 0.2*(p(out.get("i")) or 1)),
            "dv_coup": p(out.get("dv_coup") or 0.02*(p(out.get("v")) or 1)),
        }
    def run_calculation(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        vin, vout, fsw, iout = cfg["vin_min"], cfg["vout"], cfg["fsw"], cfg["iout"]
        d = abs(vout) / max(1e-9, abs(vout) + vin)
        L_in = vin * d / (cfg["delta_i_in"] * fsw); L_out = abs(vout) * (1 - d) / (cfg["delta_i_out"] * fsw)
        I_coup_rms = iout; C_coup = I_coup_rms * d / (cfg["dv_coup"] * fsw)
        v_switch = abs(vout) + vin
        i_rms, i_pk = estimate_switch_currents_boost(vin, abs(vout), iout, d, cfg["delta_i_in"], cfg["eff"])
        mosfets = recommend_mosfets(v_switch, i_rms, i_pk, fsw)
        losses = mosfet_loss_estimate(v_switch, i_rms, i_pk, fsw, {'rds_on_mohm': 15, 'tr_ns': 15, 'tf_ns': 15, 'qg_nC': 35, 'vgate_V': 10})
        return {
            "duty": round(d, 4), "l_in_H": L_in, "l_in_uH": round(L_in*1e6, 2),
            "l_out_H": L_out, "l_out_uH": round(L_out*1e6, 2), "c_coupling_F": C_coup, "c_coupling_uF": round(C_coup*1e6, 2),
            "vds_max_V": round(v_switch, 2), "polarity": "inverting", "losses_W": losses, "recommendations": {"mosfets": mosfets},
        }
