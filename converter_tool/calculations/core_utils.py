from __future__ import annotations
import math
from typing import Any

def parse_num(s: Any) -> float:
    """Parse numbers with optional SI suffixes (k, M, m, µ, etc.)."""
    if isinstance(s, (int, float)):
        return float(s)
    if s is None or (isinstance(s, str) and s.strip() == ""):
        return 0.0
    text = str(s).strip().replace(",", ".")
    import re
    m = re.match(r'^([+-]?\d+(?:\.\d+)?)([eE][+-]?\d+)?\s*([GMkmunpµ]?)', text)
    if not m:
        raise ValueError(f"Cannot parse number: {s}")
    base = float(m.group(1) + (m.group(2) or ""))
    suf = (m.group(3) or "").replace("µ", "u")
    mult = {"G": 1e9, "M": 1e6, "k": 1e3, "": 1.0, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}
    if suf not in mult:
        raise ValueError(f"Bad suffix in {s}")
    return base * mult[suf]

def core_ss0_min(p_out: float, f_sw: float, b_max: float, j: float = 4.0, k_phi: float = 1.0) -> float:
    """Minimal window product S·S0 (cm^4) from formula (3.70)."""
    return (p_out * k_phi) / (f_sw * b_max * j)

def primary_turns(v_in_min: float, d_max: float, b_max: float, s_core_m2: float, f_sw: float) -> int:
    """Primary turns requirement for single-ended topologies (15.19)."""
    w1 = (v_in_min * d_max) / (b_max * s_core_m2 * f_sw)
    return max(1, math.ceil(w1))

def ccm_check(l_value: float, i_out: float, delta_i: float, f_sw: float) -> bool:
    """Return True if the inductor current is in CCM for the given ripple."""
    current_ripple = delta_i
    return current_ripple <= 0.4 * i_out


def l_out_forward_like(vout: float, d_max: float, fsw: float, delta_i: float, full_wave: bool=True) -> float:
    """Output inductor for forward-like topologies (forward, 2T forward, push-pull, half/full-bridge).
    If full_wave=True, account for 2× ripple frequency (center-tapped or bridge full-wave), i.e., divide by 2.
    L ≈ Vout*(1 - D_max)/(ΔI * f_sw * (2 if full_wave else 1)).
    """
    denom = max(1e-12, delta_i * fsw * (2.0 if full_wave else 1.0))
    return max(1e-12, vout * (1.0 - d_max) / denom)

def cout_from_tri_ripple(delta_i: float, dv_out: float, fsw: float, pulses_per_period: int = 1) -> float:
    """Capacitance to absorb triangular inductor ripple: ΔV ≈ ΔI/(8*C*f_ripple).
    f_ripple = pulses_per_period * f_sw. For full-wave rectified outputs use 2.
    """
    f_ripple = max(1e-3, fsw * max(1, pulses_per_period))
    return max(1e-12, delta_i / (8.0 * dv_out * f_ripple))

def cin_min_dc(pout: float, vin_min: float, eff: float, d_max: float, fsw: float, dv_in: float) -> float:
    """Minimum input capacitance for DC source by charge balance:
    Cin_min ≈ I_in * D / (ΔV_in * f_sw), where I_in ≈ Pout/(η*Vin_min).
    """
    eff = max(0.05, min(0.999, eff or 0.9))
    i_in = max(1e-9, pout / (eff * max(1e-3, vin_min)))
    return max(1e-12, i_in * max(0.0, d_max) / (max(1e-6, dv_in) * fsw))

def vrrm_forward_like(vin_max: float, n_ps: float, vout: float, diode_drop: float=0.5) -> float:
    """Approximate secondary diode reverse voltage for forward-like topologies:
    VRRM ≈ Vin_max / n_ps + Vout + Vd (center-tapped or bridge rectifier).
    """
    return vin_max / max(1e-9, n_ps) + vout + max(0.0, diode_drop)


# === Loss and recommendation helpers ===

def estimate_primary_currents_forward_like(n_ps: float, iout: float, d: float, delta_i: float) -> tuple:
    """Estimate primary RMS and peak currents for forward-like CCM.
    Primary current during ON ≈ Isec (≈ Iout) * n_ps. RMS over period ≈ I_on * sqrt(D).
    Peak ≈ I_on + 0.5*ΔI * n_ps.
    """
    i_on = max(0.0, iout) * max(1e-9, n_ps)
    i_rms = i_on * math.sqrt(max(0.0, d))
    i_pk = i_on + 0.5 * max(0.0, delta_i) * max(1e-9, n_ps)
    return i_rms, i_pk

def mosfet_loss_estimate(vds: float, i_rms: float, i_pk: float, fsw: float, mosfet: dict, tC: float = 80.0) -> dict:
    """Basic MOSFET loss model: conduction, switching, gate drive.
    Rds_on scaled with temp coef from 25°C to tC.
    Psw ≈ 0.5 * Vds * Ipk * (tr+tf) * fsw * k * 1e-9 * 2  (two transitions per cycle).
    Pg  ≈ Qg * Vgate * fsw * 1e-9.
    """
    R25 = mosfet.get('rds_on_mohm', 50) * 1e-3
    alpha = mosfet.get('rds_temp_coeff', 0.004)
    R_T = R25 * (1.0 + alpha * (tC - mosfet.get('rds_temp_C', 25)))
    p_cond = (i_rms ** 2) * R_T
    tr = mosfet.get('tr_ns', 20.0)
    tf = mosfet.get('tf_ns', 40.0)
    k = mosfet.get('k_sw_overlap', 1.0)
    p_sw = 0.5 * vds * i_pk * (tr + tf) * fsw * 1e-9 * k * 2.0
    qg = mosfet.get('qg_nC', 50.0)
    vg = mosfet.get('vgate_V', 10.0)
    p_gate = qg * vg * fsw * 1e-9
    return {'P_cond_W': p_cond, 'P_sw_W': p_sw, 'P_gate_W': p_gate, 'P_total_W': p_cond + p_sw + p_gate}


def recommend_mosfets(vds_req: float, i_rms: float, i_pk: float, fsw: float, topn: int = 3) -> list:
    """Pick best MOSFETs from library by total estimated loss with Vds margin >=20%."""
    try:
        from pathlib import Path as _Path
        import json as _json
        lib_path = _Path(__file__).resolve().parent.parent / 'mosfet_library.json'
        lib = _json.loads(lib_path.read_text(encoding='utf-8'))
        cands = []
        for m in lib.get('mosfets', []):
            try:
                if float(m.get('vds_V', 0)) >= 1.2 * float(vds_req):
                    loss = mosfet_loss_estimate(vds_req, i_rms, i_pk, fsw, m)
                    cands.append({'name': m.get('name'), 'vds_V': m.get('vds_V'), 'loss': loss})
            except Exception:
                continue
        cands.sort(key=lambda x: x['loss']['P_total_W'])
        return cands[:topn]
    except Exception:
        return []

def recommend_cores(ss0_min_cm4: float, bmax_req: float, topn: int = 3) -> list:
    """Select cores by area product Ae*Aw >= required S·S0 (converted to mm^4) and Bmax >= req."""
    try:
        from pathlib import Path as _Path
        import json as _json
        required_mm4 = max(0.0, float(ss0_min_cm4)) * 10000.0
        lib_path = _Path(__file__).resolve().parent.parent / 'core_library.json'
        lib = _json.loads(lib_path.read_text(encoding='utf-8'))
        res = []
        for c in lib.get('cores', []):
            try:
                Ae = float(c.get('Ae_mm2') or 0.0)
                Aw = float(c.get('Aw_mm2') or 0.0)
                ap = Ae * Aw
                bmax = float(c.get('Bmax_T') or 0.0)
            except Exception:
                continue
            if ap >= required_mm4 and bmax + 1e-9 >= bmax_req:
                over = ap / required_mm4 if required_mm4 > 0 else float('inf')
                res.append({'core': c, 'ap_mm4': ap, 'overhead': over})
        res.sort(key=lambda x: x['ap_mm4'])
        out = []
        for r in res[:topn]:
            c = r['core']
            out.append({
                'vendor': c.get('vendor'),
                'series': c.get('series'),
                'size': c.get('size'),
                'material': c.get('material'),
                'Ae_mm2': c.get('Ae_mm2'),
                'Aw_mm2': c.get('Aw_mm2'),
                'overhead': round(r['overhead'], 3),
            })
        return out
    except Exception as e:
        return []

def estimate_switch_currents_buck(iout: float, d: float, delta_i: float) -> tuple:
    """Buck: switch conducts during D with ~inductor current; Irms ≈ Iout*sqrt(D)."""
    i_rms = max(0.0, iout) * math.sqrt(max(0.0, d))
    i_pk = max(0.0, iout) + 0.5*max(0.0, delta_i)
    return i_rms, i_pk

def estimate_switch_currents_boost(vin: float, vout: float, iout: float, d: float, delta_i: float, eff: float=0.95) -> tuple:
    """Boost-family: switch carries input inductor current during D. Iin ≈ Vo*Io/(η*Vin)."""
    i_in = (abs(vout)*iout)/(max(1e-9, eff)*max(1e-9, vin))
    i_rms = i_in * math.sqrt(max(0.0, d))
    i_pk = i_in + 0.5*max(0.0, delta_i)
    return i_rms, i_pk
