
# -*- coding: utf-8 -*-
# NOTE (2025-08-15): Zero/pole reporting strictly follows the method from ON Semiconductor TL431 notes:
# Type1: fz = 1/(2π R1·C1), fp = 1/(2π Rpullup·(C2+Copto))
# Type2_fast: same formulas as Type1 (manual override allowed)
# Type2: fz = 1/(2π R2·C1), fp = 1/(2π Rpullup·(C2+Copto))
# Type3: fz1 = 1/(2π R2·C1), fz2 = 1/(2π R1·C3), fp1 = 1/(2π R3·C3), fp2 = 1/(2π Rpullup·(C2+Copto))
# f_opto is no longer calculated or shown; Copto is taken from input and summed with C2.

"""
Optocoupler/TL431 compensation synthesizer.

Implements Type1, Type2 (fast-lane and no fast-lane), and Type3 (no fast-lane)
per ON Semiconductor application material for TL431-based feedback.

This version is written to be robust and deterministic for the GUI:
- Auto‑tune has highest priority.
- If Auto‑tune + Manual zeros/poles are both enabled: pick R/C so that the
  *resulting* zeros/poles match manual targets as closely as possible within
  R/C ranges and Zener current constraints; report actual zeros/poles from
  the final component values.
- If Auto‑tune enabled and Manual off: synthesize from (fc, G(fc), Boost).
- If Auto‑tune off and Manual on: directly realize manual zeros/poles with
  preferred R in range and compute C; then clamp to ranges and recompute actual f.
- Zener network (Rz, Vz) is referenced to Vout (NOT Vdd).

Returned report contains ONLY:
  - Final component values (respecting ranges and Iz constraints)
  - Zeros and poles (actual, from final values)
  - f_opto, fc, |G(fc)| and phase at fc

Public API used by GUI:
  - dataclass InputParams
  - compute_optocoupler(params: InputParams) -> dict with {"report_text": str}
"""

from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
import math

TwoPi = 2.0 * math.pi

# ---------- Helpers ----------
def _clamp(x, lo, hi):
    return max(lo, min(hi, x))

def _geom_mid(lo, hi):
    if lo > 0 and hi > 0:
        return math.sqrt(lo*hi)
    return 0.5*(lo+hi)

def _safe(x, eps=1e-12):
    return x if abs(x) > eps else eps

def _rc_freq(R, C):
    return 1.0/(TwoPi*R*C)

def _c_for_freq(f, R):
    return 1.0/(TwoPi*_safe(R)*_safe(f))

def _r_for_freq(f, C):
    return 1.0/(TwoPi*_safe(C)*_safe(f))

def _fz_fp_type1_from_values(R1, C1, Rpullup, C2, Copto):
    # fz = 1/(2π R1 C1); fp = 1/(2π Rpullup (C2+Copto))
    fz = _rc_freq(R1, C1) if (R1 and C1) else 0.0
    fp = _rc_freq(Rpullup, (C2 or 0.0) + (Copto or 0.0)) if Rpullup else 0.0
    return fz, fp

def _fz_fp_type2_from_values(R2, C1, Rpullup, C2, Copto):
    # fz = 1/(2π R2 C1); fp = 1/(2π Rpullup (C2+Copto))
    fz = _rc_freq(R2, C1) if (R2 and C1) else 0.0
    fp = _rc_freq(Rpullup, (C2 or 0.0) + (Copto or 0.0)) if Rpullup else 0.0
    return fz, fp

def _fz_fp_type3_from_values(R2, C1, R1, C3, R3, Rpullup, C2, Copto):
    # fz1 = 1/(2π R2 C1); fz2 = 1/(2π R1 C3)
    # fp1 = 1/(2π R3 C3); fp2 = 1/(2π Rpullup (C2+Copto))
    fz1 = _rc_freq(R2, C1) if (R2 and C1) else 0.0
    fz2 = _rc_freq(R1, C3) if (R1 and C3) else 0.0
    fp1 = _rc_freq(R3, C3) if (R3 and C3) else 0.0
    fp2 = _rc_freq(Rpullup, (C2 or 0.0) + (Copto or 0.0)) if Rpullup else 0.0
    return fz1, fz2, fp1, fp2

def _a_from_boost_deg(phi_deg: float) -> float:
    """Lead factor a from single-stage boost phi (in degrees)."""
    phi = math.radians(max(0.0, phi_deg))
    t = math.tan(phi)
    return t + math.sqrt(t*t + 1.0)

def _phase_mag_from_factors(w: float, zeros: List[float], poles: List[float]) -> Tuple[float,float]:
    """Return (mag_lin, phase_deg) for product Π sqrt(1+(w/wz)^2) / Π sqrt(1+(w/wp)^2)"""
    mag = 1.0
    phase = 0.0
    for fz in zeros:
        wz = TwoPi*_safe(fz)
        mag *= math.sqrt(1.0 + (w/_safe(wz))**2)
        phase += math.degrees(math.atan(w/_safe(wz)))
    for fp in poles:
        wp = TwoPi*_safe(fp)
        mag /= math.sqrt(1.0 + (w/_safe(wp))**2)
        phase -= math.degrees(math.atan(w/_safe(wp)))
    return mag, phase

def _choose_R_C_for_f(f_target: float, R_min: float, R_max: float, C_min: float, C_max: float) -> Tuple[float,float,float]:
    """
    Heuristic: pick R near geometric mid of [R_min,R_max] so that C ends up in [C_min,C_max].
    If computed C is out of range, adjust R to bring C into range, then recompute actual f.
    Return (R, C, f_actual).
    """
    R_pref = _geom_mid(R_min, R_max)
    C = _c_for_freq(f_target, R_pref)
    if C < C_min:
        # Need more C -> increase R
        R = _clamp(_r_for_freq(f_target, C_min), R_min, R_max)
        C = _c_for_freq(f_target, R)
    elif C > C_max:
        # Need less C -> decrease R
        R = _clamp(_r_for_freq(f_target, C_max), R_min, R_max)
        C = _c_for_freq(f_target, R)
    else:
        R = _clamp(R_pref, R_min, R_max)
        C = _clamp(C, C_min, C_max)
    f_actual = _rc_freq(R, C)
    return R, C, f_actual

def _compute_rz(vout, vz, iz_min, iz_max, ibias_tl431, ifb_req, ctr_min):
    """
    Right-side feed from Vout through Rz into zener Vz that biases TL431+LED.
    Load current at nominal: Ibias_TL431 + Iled_dc_req (≃ Ifb/CTR_min).
    Choose target Iz as geometric mid of [iz_min, iz_max], compute Rz.
    If vout <= vz, return None.
    """
    if vout <= vz + 1e-6:
        return None, 0.0, 0.0
    i_led = ifb_req/_safe(ctr_min)
    i_load = ibias_tl431 + i_led
    iz_target = _geom_mid(max(iz_min, 1e-6), max(iz_max, 2e-6))
    rz = (vout - vz)/_safe(iz_target + i_load)
    # Estimate actual Iz with this Rz:
    iz_actual = max((vout - vz)/_safe(rz) - i_load, 0.0)
    return max(rz, 1.0), iz_target, iz_actual

# ---------- Public dataclass ----------
@dataclass
class InputParams:
    # Supply/plant
    v_out: float
    f_sw: float
    vdd: float
    r_pullup: float
    ctr_min: float
    c_opto_nf: float
    v_ref: float
    v_f_led: float
    vce_sat: float
    i_div_uA: float
    v_bias_zener: float
    i_bias_mA: float
    vfb: float
    # Loop shaping targets
    fc: float
    gc_db: float
    boost_deg: float
    comp_type: str  # "type1","type2_fast","type2","type3"
    # Manual zeros/poles
    manual_enable: bool
    manual_fz_hz: float
    manual_fp_hz: float
    manual_fz2_hz: float
    manual_fp2_hz: float
    # Auto-tune
    auto_tune: bool
    plant_rhpz_hz: float = 0.0
    plant_flc_hz: float = 0.0
    r_min: float = 200.0
    r_max: float = 200e3
    c_min: float = 100e-12
    c_max: float = 1e-6
    iz_min: float = 2e-3
    iz_max: float = 15e-3

# ---------- Core design routines ----------
def _base_quantities(p: InputParams):
    Copto = max(p.c_opto_nf, 0.0)*1e-9
    f_opto = None  # per spec: do not compute/display f_opto; use Copto only
    # Divider on secondary
    Ibridge = max(p.i_div_uA, 1.0)*1e-6
    Rlower = p.v_ref/_safe(Ibridge)
    R1 = (p.v_out - p.v_ref)/_safe(Ibridge)
    # DC sink current needed at Vfb:
    Ifb = max((p.vdd - p.vfb)/_safe(p.r_pullup), 0.0)
    Iled_dc_req = Ifb/_safe(p.ctr_min)
    # Bias resistor on secondary
    Rbias = (p.v_out - p.v_ref - p.v_f_led)/_safe((p.i_bias_mA*1e-3) + Iled_dc_req)
    return Copto, f_opto, R1, Rlower, Ifb, Iled_dc_req, Rbias

def _mid_gain(Rled, p: InputParams):
    return p.ctr_min*_safe(p.r_pullup)/_safe(Rled)

def _realize_single_lead_lag(fz_target, fp_target, R_for_zero_range, C_range, r_fixed_for_pole, Copto):
    # zero via Rz_comp (R2) + C1 (series to TL431 path) -> fz = 1/(2π R2 C1)
    Rmin, Rmax = R_for_zero_range
    Cmin, Cmax = C_range
    R2, C1, fz = _choose_R_C_for_f(fz_target, Rmin, Rmax, Cmin, Cmax)
    # pole via Rpullup || C2 (collector)
    C2 = _c_for_freq(fp_target, r_fixed_for_pole)
    # account for Copto already present:
    C2_eff = max(C2 - Copto, 0.0)
    fp = _rc_freq(r_fixed_for_pole, Copto + C2_eff) if (Copto + C2_eff)>0 else 0.0
    return R2, C1, fz, C2_eff, fp


def _type1(p: InputParams) -> Dict:
    Copto, f_opto, R1, Rlower, Ifb, Iled_dc_req, Rbias = _base_quantities(p)
    # DC bound for RLED using fast-lane with Vout
    num = max(p.v_out - p.v_f_led - p.v_ref, 1e-6)
    den = max(p.vdd - p.vce_sat + (p.i_bias_mA*1e-3)*p.ctr_min*p.r_pullup, 1e-6)
    rled_max = (num/den)*p.r_pullup*p.ctr_min
    RLED = 0.85*max(1.0, rled_max)

    # Place pole at collector with C2 (if fc/G provided, reuse; else safe default at fsw/20)
    target_fp = None
    try:
        Glin = 10.0**(p.gc_db/20.0) if p.gc_db is not None else None
        target_fp = _safe(Glin * p.fc) if (Glin and p.fc) else None
    except Exception:
        target_fp = None
    if not target_fp:
        target_fp = max(p.f_sw/20.0, 10.0)

        # Collector pole per ON Semi: Cpo = CTR/(2π·G(fc)·fc·RLED); external C2 = Cpo - Copto
    C2_eff = None
    try:
        Glin = 10.0**(p.gc_db/20.0) if p.gc_db is not None else None
    except Exception:
        Glin = None
    if Glin and p.fc and RLED:
        Cpo = p.ctr_min/(TwoPi*_safe(Glin)*_safe(p.fc)*_safe(RLED))
        C2_eff = max(Cpo - Copto, 0.0)
    if C2_eff is None:
        # Fallback to placing fp at Rpullup with fsw/20 if G(fc) or fc missing
        target_fp = target_fp or max(p.f_sw/20.0, 10.0)
        C2 = _c_for_freq(target_fp, p.r_pullup)
        C2_eff = max(C2 - Copto, 0.0)
    # Auto-tune clamp
    if p.auto_tune:
        C2_eff = _clamp(C2_eff, p.c_min, p.c_max)


    # Zero via C1 across R1 (neutralize collector+opto pole roughly)
    C1 = (p.r_pullup/_safe(R1)) * (Copto + C2_eff) if R1 else 0.0
    if p.auto_tune:
        C1 = _clamp(C1, p.c_min, p.c_max)

    # Frequencies strictly by spec
    fz, fp = _fz_fp_type1_from_values(R1, C1, p.r_pullup, C2_eff, Copto)

    # Zener limiter from Vout side
    rz, iz_t, iz_a = _compute_rz(p.v_out, p.v_bias_zener, p.iz_min, p.iz_max, p.i_bias_mA*1e-3, Ifb, p.ctr_min)

    return dict(
        type="type1",
        Rpullup=p.r_pullup, RLED=RLED, Rbias=Rbias, R1=R1, Rlower=Rlower,
        C1=C1, C2=C2_eff, Rz=rz, Vz=p.v_bias_zener,
        zeros=[fz] if fz else [], poles=[fp] if fp else [],
        f_opto=None, fc=None, Gfc_db=0.0, phase_fc_deg=0.0
    )



def _type2_fast(p: InputParams, manual: Optional[Tuple[float,float]]=None) -> Dict:
    Copto, f_opto, R1, Rlower, Ifb, Iled_dc_req, Rbias = _base_quantities(p)
    num = max(p.v_out - p.v_f_led - p.v_ref, 1e-6)
    den = max(p.vdd - p.vce_sat + (p.i_bias_mA*1e-3)*p.ctr_min*p.r_pullup, 1e-6)
    rled_max = (num/den)*p.r_pullup*p.ctr_min
    RLED = 0.85*max(1.0, rled_max)

    if manual:
        fz_t, fp_t = manual
        # Direct synthesis from entered zeros/poles
        C1 = _c_for_freq(fz_t, R1) if (fz_t and R1) else 0.0
        C2_total = _c_for_freq(fp_t, p.r_pullup) if (fp_t and p.r_pullup) else 0.0
        C2_eff = max(C2_total - Copto, 0.0)
    else:
        # On Semi method: fp = [tan(Boost)+sqrt(tan^2+1)]*fc ; fz = fc^2/fp
        a = _a_from_inputs(getattr(p, 'gc_db', None), p.boost_deg)
        fp_t = _safe(a) * _safe(p.fc)
        fz_t = (_safe(p.fc)**2) / _safe(fp_t)
        C2_total = _c_for_freq(fp_t, p.r_pullup) if p.r_pullup else 0.0
        C2_eff = max(C2_total - Copto, 0.0)
        C1 = _c_for_freq(fz_t, R1) if R1 else 0.0

    # Auto-tune: clamp component values into ranges
    if p.auto_tune:
        C1 = _clamp(C1, p.c_min, p.c_max)
        C2_eff = _clamp(C2_eff, p.c_min, p.c_max)

    # Recompute actual zeros/poles from values (post-processing also does this)
    fz, fp = _fz_fp_type1_from_values(R1, C1, p.r_pullup, C2_eff, Copto)
    rz, iz_t, iz_a = _compute_rz(p.v_out, p.v_bias_zener, p.iz_min, p.iz_max, p.i_bias_mA*1e-3, Ifb, p.ctr_min)

    return dict(
        type="type2_fast",
        Rpullup=p.r_pullup, RLED=RLED, Rbias=Rbias, R1=R1, Rlower=Rlower,
        C1=C1, C2=C2_eff, Rz=rz, Vz=p.v_bias_zener,
        zeros=[fz] if fz else [], poles=[fp] if fp else [],
        R2=None, R3=None, C3=None,
        f_opto=None, fc=None, Gfc_db=0.0, phase_fc_deg=0.0
    )




def _type2_no_fast(p: InputParams, manual: Optional[Tuple[float,float]]=None) -> Dict:
    Copto, f_opto, R1, Rlower, Ifb, Iled_dc_req, Rbias = _base_quantities(p)
    # No fast lane; RLED bounded by Vz path
    num = max(p.v_bias_zener - p.v_f_led - p.v_ref, 1e-6)
    den = max(p.vdd - p.vce_sat + (p.i_bias_mA*1e-3)*p.ctr_min*p.r_pullup, 1e-6)
    rled_max = (num/den)*p.r_pullup*p.ctr_min
    RLED = 0.85*max(1.0, rled_max)

    # Targets for zero/pole
    if manual:
        fz_t, fp_t = manual
    else:
        a = _a_from_inputs(getattr(p, 'gc_db', None), p.boost_deg)
        fp_t = _safe(a) * _safe(p.fc)
        fz_t = (_safe(p.fc)**2) / _safe(fp_t)

    # Magnitude of shaping at fc
    mag_fac, phase_fac_deg = _phase_mag_from_factors(TwoPi*_safe(p.fc), [fz_t], [fp_t])

    # Gains split
    G2 = _safe(p.r_pullup) * _safe(p.ctr_min) / _safe(RLED)
    Glin = 10.0**(p.gc_db/20.0) if p.gc_db is not None else 1.0
    G1_target = _safe(Glin) / _safe(G2 * mag_fac)

    # Choose R2 to hit G1_target; then C1 from fz with R2
    R2 = _clamp(G1_target * _safe(R1), p.r_min, p.r_max)
    C1 = _c_for_freq(fz_t, R2) if (fz_t and R2) else 0.0

    # Collector pole; external C2 after subtracting Copto
    C2_total = _c_for_freq(fp_t, p.r_pullup) if (fp_t and p.r_pullup) else 0.0
    C2_eff = max(C2_total - Copto, 0.0)

    if p.auto_tune:
        R2 = _clamp(R2, p.r_min, p.r_max)
        C1 = _clamp(C1, p.c_min, p.c_max)
        C2_eff = _clamp(C2_eff, p.c_min, p.c_max)

    fz, fp = _fz_fp_type2_from_values(R2, C1, p.r_pullup, C2_eff, Copto)
    rz, iz_t, iz_a = _compute_rz(p.v_out, p.v_bias_zener, p.iz_min, p.iz_max, p.i_bias_mA*1e-3, Ifb, p.ctr_min)

    return dict(
        type="type2",
        Rpullup=p.r_pullup, RLED=RLED, Rbias=Rbias, R1=R1, Rlower=Rlower,
        R2=R2, C1=C1, C2=C2_eff, Rz=rz, Vz=p.v_bias_zener,
        zeros=[fz] if fz else [], poles=[fp] if fp else [],
        R3=None, C3=None,
        f_opto=None, fc=None, Gfc_db=0.0, phase_fc_deg=0.0
    )


def _type3_no_fast(p: InputParams, manual: Optional[Tuple[float,float,float,float]]=None) -> Dict:
    Copto, f_opto, R1, Rlower, Ifb, Iled_dc_req, Rbias = _base_quantities(p)
    # Use Vz bound for RLED
    num = max(p.v_bias_zener - p.v_f_led - p.v_ref, 1e-6)
    den = max(p.vdd - p.vce_sat + (p.i_bias_mA*1e-3)*p.ctr_min*p.r_pullup, 1e-6)
    rled_max = (num/den)*p.r_pullup*p.ctr_min
    RLED = 0.85*max(1.0, rled_max)

    if manual:
        fz1_t, fp1_t, fz2_t, fp2_t = manual
    else:
        a = _a_from_boost_deg(p.boost_deg/2.0)
        fp1_t = _safe(a) * _safe(p.fc)
        fp2_t = fp1_t
        fz1_t = (_safe(p.fc)**2) / _safe(fp1_t)
        fz2_t = (_safe(p.fc)**2) / _safe(fp2_t)

    # Gains
    G2 = _safe(p.r_pullup) * _safe(p.ctr_min) / _safe(RLED)
    Glin = 10.0**(p.gc_db/20.0) if p.gc_db is not None else 1.0
    _mag_fac, _phase_fac_deg = _phase_mag_from_factors(TwoPi*_safe(p.fc), [fz1_t, fz2_t], [fp1_t, fp2_t])
    G1 = _safe(Glin) / _safe(G2 * _mag_fac)

    # R2 from user's formula
    # R2 = (G1*R1*fp1/(fp1 - fz1)) * sqrt(1+(fc/fp1)^2)*sqrt(1+(fc/fp2)^2) / ( sqrt(1+(fz1/fc)^2)*sqrt(1+(fz2/fc)^2) )
    R2 = ( _safe(G1) * _safe(R1) * _safe(fp1_t) / _safe(fp1_t - fz1_t) ) *          ( math.sqrt(1.0 + (_safe(p.fc)/_safe(fp1_t))**2) * math.sqrt(1.0 + (_safe(p.fc)/_safe(fp2_t))**2) ) /          ( math.sqrt(1.0 + (_safe(fz1_t)/_safe(p.fc))**2) * math.sqrt(1.0 + (_safe(fz2_t)/_safe(p.fc))**2) )

    # Compute C3 from fz2 with R1; then R3 from fp1 to satisfy both targets
    C3 = _c_for_freq(fz2_t, R1) if (fz2_t and R1) else 0.0
    R3 = _r_for_freq(fp1_t, C3) if (fp1_t and C3) else 0.0
    C1 = _c_for_freq(fz1_t, R2) if (fz1_t and R2) else 0.0
    C2_total = _c_for_freq(fp2_t, p.r_pullup) if (fp2_t and p.r_pullup) else 0.0
    C2_eff = max(C2_total - Copto, 0.0)

    if p.auto_tune:
        # Keep fz1 target by clamping C1 only
        R2 = _clamp(R2, p.r_min, p.r_max)
        C1 = _clamp(C1, p.c_min, p.c_max)
        # Preserve fz2 and fp1 relationship:
        C3 = _clamp(C3, p.c_min, p.c_max)
        R3 = _r_for_freq(fp1_t, C3) if (fp1_t and C3) else R3
        R3 = _clamp(R3, p.r_min, p.r_max)
        C3 = _c_for_freq(fp1_t, R3) if (fp1_t and R3) else C3
        C2_eff = _clamp(C2_eff, p.c_min, p.c_max)

    fz1, fz2, fp1, fp2 = _fz_fp_type3_from_values(R2, C1, R1, C3, R3, p.r_pullup, C2_eff, Copto)
    rz, iz_t, iz_a = _compute_rz(p.v_out, p.v_bias_zener, p.iz_min, p.iz_max, p.i_bias_mA*1e-3, Ifb, p.ctr_min)

    return dict(
        type="type3",
        Rpullup=p.r_pullup, RLED=RLED, Rbias=Rbias, R1=R1, Rlower=Rlower,
        R2=R2, C1=C1, C2=C2_eff, R3=R3, C3=C3, Rz=rz, Vz=p.v_bias_zener,
        zeros=[f for f in (fz1, fz2) if f], poles=[f for f in (fp1, fp2) if f],
        f_opto=None, fc=None, Gfc_db=0.0, phase_fc_deg=0.0
    )


def compute_optocoupler(p: InputParams) -> Dict[str,str]:
    t = (p.comp_type or "type3").strip().lower()
    # Manual tuple preparation
    manual_tuple = None
    if p.manual_enable:
        if t in ("type2", "type2_fast"):
            manual_tuple = (max(p.manual_fz_hz, 1.0), max(p.manual_fp_hz, 1.0))
        elif t == "type3":
            manual_tuple = (max(p.manual_fz_hz, 1.0), max(p.manual_fp_hz, 1.0),
                            max(p.manual_fz2_hz, 1.0), max(p.manual_fp2_hz, 1.0))
    if t == "type1":
        d = _type1(p)
    elif t == "type2_fast":
        d = _type2_fast(p, manual_tuple if p.manual_enable else None)
    elif t == "type2":
        d = _type2_no_fast(p, manual_tuple if p.manual_enable else None)
    else:
        d = _type3_no_fast(p, manual_tuple if p.manual_enable else None)
    # --- Post-process zeros/poles and component visibility per user's spec ---
    # Always recompute zeros/poles from *actual* component values:
    Rpull = d.get("Rpullup", p.r_pullup)
    Copto = max(p.c_opto_nf, 0.0)*1e-9
    R1v = d.get("R1"); R2v = d.get("R2"); R3v = d.get("R3")
    C1v = d.get("C1"); C2v = d.get("C2"); C3v = d.get("C3")

    if t == "type1":
        fz, fp = _fz_fp_type1_from_values(R1v, C1v, Rpull, C2v, Copto)
        d["zeros"] = [fz] if fz else []
        d["poles"] = [fp] if fp else []
        # Remove non-existing parts per spec
        d["R2"] = None; d["R3"] = None; d["C3"] = None
        d["f_opto"] = None


    
    elif t == "type2_fast":
        # same formula as type1; manual may have set C1/C2 via upstream function
        fz, fp = _fz_fp_type1_from_values(R1v, C1v, Rpull, C2v, Copto)
        d["zeros"] = [fz] if fz else []
        d["poles"] = [fp] if fp else []
        # Remove R2 and R3/C3 in results
        d["R2"] = None; d["R3"] = None; d["C3"] = None
        d["f_opto"] = None

    elif t == "type2":
        fz, fp = _fz_fp_type2_from_values(R2v, C1v, Rpull, C2v, Copto)
        d["zeros"] = [fz] if fz else []
        d["poles"] = [fp] if fp else []
        # Remove R3/C3
        d["R3"] = None; d["C3"] = None
        d["f_opto"] = None

    else:  # type3
        fz1, fz2, fp1, fp2 = _fz_fp_type3_from_values(R2v, C1v, R1v, C3v, R3v, Rpull, C2v, Copto)
        d["zeros"] = [f for f in (fz1, fz2) if f]
        d["poles"] = [f for f in (fp1, fp2) if f]
        d["f_opto"] = None


    
    # Compute G(fc) and phase boost from zeros/poles + mid-gain
    Gfc_db = 0.0
    phase_fc = 0.0
    try:
        fc = max(p.fc, 0.0)
        zeros = d.get("zeros", []) or []
        poles = d.get("poles", []) or []
        if fc > 0.0:
            w = TwoPi*fc
            mag_fac, phase_fac_deg = _phase_mag_from_factors(w, zeros, poles)
            # Mid-band gain of optocoupler path (approx. CTR*Rpullup/RLED)
            RLED_val = d.get("RLED", None)
            Km = _mid_gain(RLED_val, p) if RLED_val else 1.0
            Gfc_db = 20.0*math.log10(max(Km*mag_fac, 1e-12))
            phase_fc = phase_fac_deg
    except Exception:
        pass
    d["Gfc_db"] = Gfc_db
    d["phase_fc_deg"] = phase_fc

    # --- Compute G(fc) and phase boost strictly from the *final* zeros/poles ---
    # We intentionally ignore the pole at the origin (integrator) and any absolute gain constants.
    # G(fc) here is the shaping magnitude of the zero/pole network only, as per the ON Semi method used in the GUI.
    d["Gfc_db"] = 0.0
    d["phase_fc_deg"] = 0.0
    try:
        fc_eval = float(p.fc) if getattr(p, "fc", None) else 0.0
    except Exception:
        fc_eval = 0.0
    if fc_eval > 0.0:
        zeros_eval = [f for f in d.get("zeros", []) if f and f > 0.0]
        poles_eval = [f for f in d.get("poles", []) if f and f > 0.0]
        if zeros_eval or poles_eval:
            w = TwoPi * fc_eval
            mag_lin, phase_deg = _phase_mag_from_factors(w, zeros_eval, poles_eval)
            mag_lin = max(mag_lin, 1e-24)  # Guard against log of non-positive
            d["Gfc_db"] = 20.0 * math.log10(mag_lin)
            d["phase_fc_deg"] = phase_deg
    # Build concise report
    lines = []
    # Components (only those that exist for the type)
    def add(name, val):
        if val is None: return
        if isinstance(val, (float,int)):
            lines.append(f"{name:7s} = {val:.6g}")
        else:
            lines.append(f"{name:7s} = {val}")
    add("Rpullup", d.get("Rpullup"))
    add("RLED",    d.get("RLED"))
    add("Rbias",   d.get("Rbias"))
    add("Rz",      d.get("Rz"))
    add("R1",      d.get("R1"))
    add("Rlower",  d.get("Rlower"))
    add("R2",      d.get("R2"))
    add("R3",      d.get("R3"))
    add("C1",      d.get("C1"))
    add("C2",      d.get("C2"))
    add("C3",      d.get("C3"))
    # Zeros/poles
    zeros = [f for f in d.get("zeros", []) if f and f>0]
    poles = [f for f in d.get("poles", []) if f and f>0]
    if zeros:
        lines.append("Zeros   = " + ", ".join(f"{f:.3g} Hz" for f in zeros))
    else:
        lines.append("Zeros   = —")
    if poles:
        lines.append("Poles   = " + ", ".join(f"{f:.3g} Hz" for f in poles))
    else:
        lines.append("Poles   = —")
    # Summary
    # fopto removed per spec
    add("fc",    d.get("fc"))
    try:
        tgt = float(p.gc_db)
    except Exception:
        tgt = None
    lines.append((f"Target G(fc)= {tgt:.3f} dB" if isinstance(tgt,(int,float)) else "Target G(fc)= —"))
    lines.append(f"Achieved G(fc)= {d.get('Gfc_db', 0.0):.3f} dB")
    lines.append(f"Phase@fc= {d.get('phase_fc_deg', 0.0):.2f} deg")

    return {"report_text": "\n".join(lines)}

def _a_from_inputs(gc_db: Optional[float], boost_deg: Optional[float]) -> float:
    """Prefer Gc(dB) if provided; otherwise use Boost. Returns 'a' >= 1."""
    try:
        if gc_db is not None:
            a = 10.0**(float(gc_db)/20.0)
            return max(a, 1.0)
    except Exception:
        pass
    return _a_from_boost_deg(boost_deg)
