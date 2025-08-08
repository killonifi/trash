#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Optocoupler feedback (TL431 + optocoupler) calculator
- Based on ON Semiconductor / Power Seminars note "The TL431 in Switching Power Supplies"
  (sections on small-signal analysis and Type-3 compensator; see the attached PDF).
- Implements the "no fast lane" approach (LED current resistor referenced to a fixed bias / zener),
  which removes the static gain limit and matches the Type‑3 recipes in the slides.

What this module does:
- Accepts default values from converter "Inputs/Outputs" (Vout, fsw) but allows full manual override.
- Computes TL431 divider, LED bias path (R_LED limit + margin), R_bias for TL431 cathode bias.
- Places Type‑3 zeros/poles at user-set frequencies (or sensible defaults near fc) and computes R/C.
- Accounts for optocoupler pole at f_opto = 1/(2π R_pullup·(C_opto + C2_eff)).
- Solves R3 (integrator leg) to meet the requested mid-band gain at fc (attenuation Gc_dB).
- Reports warnings when constraints from the PDF are violated (e.g., fc too close to f_opto).

Small‑signal model (no fast lane):
  O(s) = (CTR · Rpullup / RLED) · 1 / (1 + s · Rpullup · Cpole),  where Cpole = Copto + C2_eff
  G3(s) = (1 + s·R2·C1)(1 + s·R1·C2) / (s·R3·C3)(1 + s/fp3_term)  → here the high‑freq pole is via (R3,C3)
We set C2_eff≈C2 for the opto pole computation as in the Type‑2 derivation (C2 in parallel to Copto).

References:
- See the provided PDF "Расчет опторазвязки.PDF" (Type‑3, fast‑lane suppressed approach).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Dict, Any, Optional, Tuple, List
import math
TWOPI = 2.0*3.141592653589793

def _fmt_table(d: Dict[str, Any], title: str) -> str:
    keys = list(d.keys())
    width = max((len(k) for k in keys), default=10)
    lines = [f"== {title} =="]
    for k in keys:
        v = d[k]
        if isinstance(v, float):
            lines.append(f"{k:<{width}} : {v:.6g}")
        else:
            lines.append(f"{k:<{width}} : {v}")
    return "\n".join(lines)

from typing import Dict, Any, Optional, Tuple, List
import math

TWOPI = 2.0*3.141592653589793

def _e24_round(value: float, prefer_high: bool = False) -> float:
    """Round a resistor (Ohm) or capacitor (F) to E24. Simple 1-2-... scaling."""
    if value <= 0 or not (value < float('inf')):
        return value
    E24 = [1.0,1.1,1.2,1.3,1.5,1.6,1.8,2.0,2.2,2.4,2.7,3.0,3.3,3.6,3.9,4.3,4.7,5.1,5.6,6.2,6.8,7.5,8.2,9.1]
    exp = 0
    v = value
    # Normalize to [1,10)
    while v >= 10.0:
        v /= 10.0
        exp += 1
    while v < 1.0:
        v *= 10.0
        exp -= 1
    # Select nearest in E24
    if prefer_high:
        pick = min((e for e in E24 if e>=v), default=E24[-1])
    else:
        pick = min(E24, key=lambda e: abs(e-v))
    return pick*(10.0**exp)


@dataclass
class InputParams:
    # From core Inputs/Outputs (defaults), user may override in GUI
    v_out: float                   = 12.0      # Vout (main output), V
    f_sw: float                    = 100e3     # switching frequency, Hz (for info only)
    # Supply / optocoupler assumptions
    vdd: float                     = 5.0       # pull-up supply at phototransistor collector, V
    r_pullup: float                = 20_000.0  # collector pull-up resistor, Ohm
    ctr_min: float                 = 0.3       # CTR at the bias point (use min per PDF)
    vce_sat: float                 = 0.3       # opto transistor VCE(sat), V
    copto_nf: float                = 2.0       # opto transistor parasitic capacitance, nF (from characterization)
    # TL431 / LED path
    v_ref: float                   = 2.5       # TL431 reference, V
    v_f_led: float                 = 1.0       # LED forward voltage at bias point, V
    i_div_uA: float                = 250.0     # Divider current through TL431 network, µA
    v_bias_zener: float            = 6.2       # Zener for LED resistor referencing (no fast lane), V
    i_bias_mA: float               = 1.0       # Extra TL431 cathode bias current via Rbias, mA
    led_margin: float              = 0.85      # Use 85% of R_LED,max per PDF practice
    # Type-3 shaping
    fc: float                      = 1.0e3     # desired crossover frequency, Hz (for reference/checks)
    gc_db: float                   = -10.0     # desired total loop gain at fc from the compensator chain, dB (attenuation → negative)
    # Place zeros/poles (defaults follow the PDF's spirit; user can override from GUI)
    fz1: float                     = 0.3e3     # lower zero, Hz
    fz2: float                     = 0.9e3     # upper zero, Hz
    fp3: float                     = 3.0e3     # high-frequency compensator pole (R3,C3), Hz
    c1_nf: float                   = 10.0      # C1 (nF) for zero at fz1
    c2_nf: float                   = 4.7       # C2 (nF) for zero at fz2 (also appears in opto pole)
    c3_nf: float                   = 1.0       # C3 (nF) for pole at fp3
    # LED / TL431 operating constraints
    v_zener_present: bool          = True      # Use a bias zener node (no fast lane). If False, classical fast-lane (not implemented here).
    # New: working point and FB window
    vk_work: float                 = 2.5       # Working point at TL431 cathode, V
    vfb_min: float                 = 2.0       # Controller FB low threshold (min duty), V
    vfb_max: float                 = 4.0       # Controller FB high threshold (max duty), V
    # Selected optocoupler model name (from library)
    opto_model: str                = ""
def _calc_divider(v_out: float, v_ref: float, i_div_uA: float) -> Tuple[float,float]:
    i = max(i_div_uA, 50.0) * 1e-6
    r_low = v_ref / i
    r_up = (v_out - v_ref)/i
    return r_up, r_low

def _led_r_max(vz: float, vf: float, vref: float, vdd: float, vcesat: float, ibias_mA: float, r_pullup: float, ctr: float) -> float:
    # From PDF (no fast lane): R_LED,max = ((Vz - Vf - Vref) / (Vdd - VCEsat + Ibias*CTR*Rpullup)) * Rpullup * CTR
    ib = max(ibias_mA, 0.1)*1e-3
    num = max(vz - vf - vref, 1e-6)
    den = max(vdd - vcesat + ib*ctr*r_pullup, 1e-6)
    return (num/den) * r_pullup * ctr

def _mag_ratio(freq: float, f1: float) -> float:
    """|1 + j f/f1| magnitude."""
    x = freq/max(f1, 1e-9)
    return (1.0 + x*x) ** 0.5

def compute_optocoupler(p: InputParams) -> Dict[str, Any]:
    # Divider
    r_up, r_low = _calc_divider(p.v_out, p.v_ref, p.i_div_uA)
    # LED resistor limit and selection
    r_led_max = _led_r_max(p.v_bias_zener, p.v_f_led, p.v_ref, p.vdd, p.vce_sat, p.i_bias_mA, p.r_pullup, p.ctr_min)
    if r_led_max <= 0:
        raise ValueError("R_LED,max вычислился отрицательным/нулевым — проверьте Vbias/Vf/Vref/Vdd/Ibias.")
    r_led = p.led_margin * r_led_max

    # Frequencies and caps
    fc = max(p.fc, 1.0)
    fz1, fz2, fp3 = max(p.fz1, 1.0), max(p.fz2, 1.0), max(p.fp3, 10.0)
    c1, c2, c3 = p.c1_nf*1e-9, p.c2_nf*1e-9, p.c3_nf*1e-9
    # Resistances from zeros/pole
    r2 = 1.0/(TWOPI * fz1 * max(c1,1e-15))
    r1 = 1.0/(TWOPI * fz2 * max(c2,1e-15))
    # R3 is solved later to meet gain at fc
    # Optocoupler pole with C2 in parallel (as recommended in the slides for Type‑2; we use same approximation here)
    c_opto = p.copto_nf*1e-9
    c_pole = c_opto + c2
    f_opto = 1.0/(TWOPI * p.r_pullup * max(c_pole,1e-15))

    # Mid-band gain composition at fc
    gc_target = 10.0**(p.gc_db/20.0)  # linear
    g2 = (p.r_pullup * p.ctr_min) / max(r_led, 1e-9)  # extra gain term from O(s)
    g_opto = 1.0/_mag_ratio(fc, f_opto)               # |1/(1 + jf/f_opto)|

    # The Type‑3 block magnitude at fc = [(1+j f/fz1)(1+j f/fz2)] / [j f/fpI · (1+j f/fp3)]
    # Its magnitude is:  (|1+j f/fz1|·|1+j f/fz2|) / [(f/fpI)·|1+j f/fp3|]
    # Let fpI = 1/(2π R3 C3). Solve for fpI to hit the requested |Gc(fc)|:
    num = _mag_ratio(fc, fz1) * _mag_ratio(fc, fz2)
    den_const = _mag_ratio(fc, fp3)
    g_const = g2 * g_opto * (num / den_const)
    # gc_target = g_const * (fpI/fc)  →  fpI = gc_target * fc / g_const
    fpI = max(gc_target * fc / max(g_const, 1e-18), 1.0)
    r3 = 1.0/(TWOPI * fpI * max(c3,1e-15))

    # Round to E24 for practicality
    r1_e24 = _e24_round(r1)
    r2_e24 = _e24_round(r2)
    c1_e24 = _e24_round(c1, prefer_high=True)
    c2_e24 = _e24_round(c2, prefer_high=True)
    c3_e24 = _e24_round(c3, prefer_high=True)
    # Re-solve R3 with rounded C3 to hit target more closely
    den_const2 = _mag_ratio(fc, fp3)
    g_const2 = g2 * (1.0/_mag_ratio(fc, 1.0/(TWOPI * p.r_pullup * (p.copto_nf*1e-9 + c2_e24)))) * (num / den_const2)
    fpI2 = max(gc_target * fc / max(g_const2, 1e-18), 1.0)
    r3 = 1.0/(TWOPI * fpI2 * max(c3_e24,1e-15))
    r3_e24 = _e24_round(r3)

    # Re-evaluate achieved gains with rounded parts
    fz1_eff = 1.0/(TWOPI*r2_e24*max(c1_e24,1e-15))
    fz2_eff = 1.0/(TWOPI*r1_e24*max(c2_e24,1e-15))
    fp3_eff = 1.0/(TWOPI*r3_e24*max(c3_e24,1e-15))
    f_opto_eff = 1.0/(TWOPI * p.r_pullup * (p.copto_nf*1e-9 + c2_e24))
    g_comp = ( _mag_ratio(fc, fz1_eff) * _mag_ratio(fc, fz2_eff) ) / ( (fc/max(fpI,1.0)) * _mag_ratio(fc, fp3_eff) )
    g_total = g2 * (1.0/_mag_ratio(fc, f_opto_eff)) * g_comp
    g_total_db = 20.0*math.log10(max(g_total,1e-18))

    # Bias path
    ibias = max(p.i_bias_mA, 0.1)*1e-3
    r_bias = (p.v_bias_zener - p.v_ref)/ibias if p.v_zener_present else None

    warnings: List[str] = []
    if fc > 0.3 * f_opto:
        warnings.append(f"fc ({fc:.0f} Гц) близко к полю оптрона ({f_opto:.0f} Гц) — «фазовый потолок» и недостаток запаса возможны.")
    if r_led > r_led_max:
        warnings.append("R_LED выбран выше R_LED,max. Уменьшите R_LED либо увеличьте CTR/уменьшите R_pullup.")
    if p.ctr_min < 0.2:
        warnings.append("CTR(min) выглядит заниженным — перепроверьте даташит/рабочую точку.")
    if p.i_div_uA < 150:
        warnings.append("Ток делителя TL431 <150 µA — точность TL431 может деградировать (см. PDF).")

    out: Dict[str, Any] = {
        "inputs": asdict(p),
        "derived": {
            "R_upper_Ohm": r_up,
            "R_lower_Ohm": r_low,
            "R_LED_max_Ohm": r_led_max,
            "R_LED_sel_Ohm": r_led,
            "G2_extra": g2,
            "f_opto_Hz": f_opto,
            "fpI_Hz": fpI,
        },
        "type3_network": {
            "R1_Ohm": r1_e24, "C2_F": c2_e24, "fz2_Hz": fz2_eff,
            "R2_Ohm": r2_e24, "C1_F": c1_e24, "fz1_Hz": fz1_eff,
            "R3_Ohm": r3_e24, "C3_F": c3_e24, "fp3_Hz": fp3_eff,
        },
        "achieved_at_fc": {
            "G_total_dB": g_total_db,
            "G_total_lin": g_total,
            "G_target_dB": p.gc_db,
            "f_opto_eff_Hz": f_opto_eff,
        },
        "bias": {
            "R_bias_Ohm": r_bias,
            "I_bias_A": ibias,
        },
        "notes": [
            "Модель: Type‑3, suppression fast‑lane; C2 учитывается в полюсе оптопары (C_opto + C2).",
            "R3 выбрано для выполнения целевого G(fc) в точке fc."
        ],
        "warnings": warnings,
    }
    return out
