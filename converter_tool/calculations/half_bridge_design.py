
from __future__ import annotations
import math
from typing import Dict, Any
from .base import ConverterDesign
from .core_utils import (
    parse_num, primary_turns, l_out_forward_like, cout_from_tri_ripple, cin_min_dc, vrrm_forward_like,
    core_ss0_min, ccm_check, estimate_primary_currents_forward_like, recommend_mosfets, recommend_cores, mosfet_loss_estimate
)

class HalfBridgeDesign(ConverterDesign):
    @staticmethod
    def normalize_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
        p = lambda x: parse_num(x); out = (cfg.get('outputs') or [{}])[0]
        return {
            'vin_min': p(cfg.get('input', {}).get('vin_min')), 'vin_max': p(cfg.get('input', {}).get('vin_max')),
            'fsw': p(cfg.get('input', {}).get('fsw')), 'duty_max': p(cfg.get('input', {}).get('duty_max') or 0.45),
            'eff': p(cfg.get('input', {}).get('eff') or 0.94), 'cin_vrip': p(cfg.get('input', {}).get('cin_vrip') or 0.05*max(1.0, p(cfg.get('input', {}).get('vin_min') or 0))),
            'vout': p(out.get('v')), 'iout': p(out.get('i')), 'ripple_v': p(out.get('ripple_v') or 0.01*max(1.0, p(out.get('v') or 0))),
            'diode_drop': p(out.get('diode_drop') or 0.5), 'bmax': p(cfg.get('core', {}).get('bmax_T') or 0.2), 'ae_m2': p(cfg.get('core', {}).get('ae_mm2') or 60.0)*1e-6,
        }
    def run_calculation(self, c: Dict[str, Any]) -> Dict[str, Any]:
        vin_min, vin_max, fsw, d, eff = c['vin_min'], c['vin_max'], c['fsw'], c['duty_max'], c['eff']
        vout, iout, vd = c['vout'], c['iout'], c['diode_drop']; bmax, ae = c['bmax'], c['ae_m2']
        n_ps = (vin_min * d) / (vout + vd)
        w1 = primary_turns(vin_min/2.0, d, bmax, ae, fsw); w2 = max(1, math.ceil(w1 / max(1e-9, n_ps)))
        vds = vin_max; pout = vout * iout
        delta_i = 0.35 * iout
        l_min = l_out_forward_like(vout, d, fsw, delta_i, full_wave=True)
        c_out = cout_from_tri_ripple(delta_i, c['ripple_v'], fsw, pulses_per_period=2)
        mode = 'CCM' if ccm_check(l_min, iout, delta_i, fsw) else 'DCM'
        c_in = cin_min_dc(pout, vin_min, eff, d, fsw, c['cin_vrip'])
        vrrm = vrrm_forward_like(vin_max, n_ps, vout, vd)
        ss0 = core_ss0_min(pout, fsw, bmax)
        i_rms, i_pk = estimate_primary_currents_forward_like(n_ps, iout, d, delta_i)
        losses = mosfet_loss_estimate(vds, i_rms, i_pk, fsw, {'rds_on_mohm': 35, 'tr_ns': 20, 'tf_ns': 40, 'qg_nC': 40, 'vgate_V': 10})
        mosfets = recommend_mosfets(vds, i_rms, i_pk, fsw); cores = recommend_cores(ss0, bmax)
        return {
            'turns_ratio_Np_over_Ns': round(n_ps, 4),
            'primary_turns': int(w1), 'secondary_turns': int(w2),
            'vds_max_V': round(vds, 2), 'vrrm_sec_V': round(vrrm, 2),
            'l_out_min_H': l_min, 'l_out_min_uH': round(l_min*1e6, 2),
            'c_out_min_F': c_out, 'c_out_min_uF': round(c_out*1e6, 2),
            'cin_min_F': c_in, 'cin_min_uF': round(c_in*1e6, 2),
            'output_current_mode': mode, 'SS0_min_cm4': round(ss0, 3),
            'losses_W': losses, 'recommendations': {'mosfets': mosfets, 'cores': cores},
        }
