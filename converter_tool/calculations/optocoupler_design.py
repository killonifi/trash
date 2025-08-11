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

def _ti_fb_window(vdd: float, r_pullup: float, vfb_min: float, vfb_max: float):
    r_min = max(r_pullup*0.99, 1e-3)
    r_max = max(r_pullup*1.01, 1e-3)
    i_max = max((vdd - vfb_min)/r_min, 0.0)
    i_min = max((vdd - vfb_max)/r_max, 0.0)
    return i_min, i_max

def _i_led_required(i_collector_max: float, ctr_min: float) -> float:
    return i_collector_max/max(ctr_min, 1e-9)

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
    fp2: float                     = 2.0e3     # additional HF pole (Type‑2/3), Hz
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
    comp_type: str                 = "type3"
def _calc_divider(v_out: float, v_ref: float, i_div_uA: float) -> Tuple[float,float]:
    i = max(i_div_uA, 50.0) * 1e-6
    r_low = v_ref / i
    r_up = (v_out - v_ref)/i
    return r_up, r_low

def _led_r_max_nofastlane(vz: float, vf: float, vref: float, vdd: float, vcesat: float, ibias_mA: float, r_pullup: float, ctr: float) -> float:
    # From PDF (no fast lane): R_LED,max = ((Vz - Vf - Vref) / (Vdd - VCEsat + Ibias*CTR*Rpullup)) * Rpullup * CTR
    ib = max(ibias_mA, 0.1)*1e-3
    num = max(vz - vf - vref, 1e-6)
    den = max(vdd - vcesat + ib*ctr*r_pullup, 1e-6)
    return (num/den) * r_pullup * ctr


def _led_r_max_fastlane(vout: float, vf: float, vref: float, vdd: float, vcesat: float, ibias_mA: float, r_pullup: float, ctr: float) -> float:
    """Maximum LED resistor when LED is tied to Vout ("fast lane" present).
    R_LED,max = ((Vout - Vf - Vref) / (Vdd - VCEsat + Ibias·CTR·Rpullup)) · Rpullup · CTR
    (per ON Semiconductor TL431 seminar)."""
    ib = max(ibias_mA, 0.0)*1e-3
    num = max(vout - vf - vref, 1e-6)
    den = max(vdd - vcesat + ib*ctr*r_pullup, 1e-6)
    return (num/den) * r_pullup * ctr
def _mag_ratio(freq: float, f1: float) -> float:
    """|1 + j f/f1| magnitude."""
    x = freq/max(f1, 1e-9)
    return (1.0 + x*x) ** 0.5


def _compute_type1(p, r_led, r_up, r_low):
    """Type-1: 1 pole at origin (integrator), no phase boost."""
    import math
    fc = max(p.fc, 1.0)
    c1 = max(p.c1_nf*1e-9, 1e-12)  # integrator cap
    f_opto = 1.0/(TWOPI * p.r_pullup * (p.copto_nf*1e-9))
    g2 = (p.r_pullup * p.ctr_min) / max(r_led, 1e-9)
    g_opto = 1.0/_mag_ratio(fc, f_opto)
    gc_target = 10.0**(p.gc_db/20.0)
    fpI = max(gc_target * fc / max(g2*g_opto, 1e-18), 1.0)
    r1 = 1.0/(TWOPI * fpI * c1)
    r1_e = _e24_round(r1); c1_e = _e24_round(c1, prefer_high=True)
    fpI_e = 1.0/(TWOPI * max(r1_e,1e-3) * max(c1_e,1e-15))
    f_opto_e = 1.0/(TWOPI * p.r_pullup * (p.copto_nf*1e-9))
    g_total = g2 * (1.0/_mag_ratio(fc, f_opto_e)) * (fpI_e/fc)
    g_total_db = 20.0*math.log10(max(g_total,1e-18))
    return {
        "type": "Type-1 (fast lane)",
        "parts": {"R1_Ohm": r1_e, "C1_F": c1_e},
        "freqs": {"fpI_Hz": fpI_e, "f_opto_Hz": f_opto_e},
        "gain_at_fc_dB": g_total_db,
    }


def _compute_type2(p, r_led, r_up, r_low):
    """Type-2A (per user's requirement): integrator (R1,C1) + one zero (R2,C1).
    No additional HF pole (no R3/C3)."""
    import math
    fc = max(p.fc, 1.0)
    fz = max(p.fz1, 1.0)
    c1 = max(p.c1_nf*1e-9, 1e-12)
    # R2 from desired zero
    r2 = 1.0/(TWOPI * fz * c1)
    # Optocoupler pole (collector capacitance only)
    f_opto = 1.0/(TWOPI * p.r_pullup * (p.copto_nf*1e-9))
    g2 = (p.r_pullup * p.ctr_min) / max(r_led, 1e-9)
    g_opto = 1.0/_mag_ratio(fc, f_opto)
    gc_target = 10.0**(p.gc_db/20.0)
    # |Gcomp(fc)| = |1 + j fc/fz| / (fc/fpI) = mag_ratio(fc,fz) * fpI/fc
    fpI = max((gc_target * fc) / max(g2 * g_opto * _mag_ratio(fc, fz), 1e-18), 1.0)
    r1 = 1.0/(TWOPI * fpI * c1)
    # E24 rounding
    r1_e = _e24_round(r1); r2_e = _e24_round(r2)
    c1_e = _e24_round(c1, prefer_high=True)
    # Recompute achieved frequencies/gain
    fz_e = 1.0/(TWOPI * max(r2_e,1e-3) * max(c1_e,1e-15))
    fpI_e = 1.0/(TWOPI * max(r1_e,1e-3) * max(c1_e,1e-15))
    f_opto_e = 1.0/(TWOPI * p.r_pullup * (p.copto_nf*1e-9))
    g_comp = _mag_ratio(fc, fz_e) * (fpI_e/max(fc,1.0))
    g_total = g2 * (1.0/_mag_ratio(fc, f_opto_e)) * g_comp
    g_total_db = 20.0*math.log10(max(g_total,1e-18))
    return {
        "type": "Type-2 (fast lane present, no HF pole)",
        "parts": { "R1_Ohm": r1_e, "R2_Ohm": r2_e, "C1_F": c1_e },
        "freqs": { "fz_Hz": fz_e, "fpI_Hz": fpI_e, "f_opto_Hz": f_opto_e },
        "gain_at_fc_dB": g_total_db,
    }


def _compute_type3(p, r_led, r_up, r_low):
    """Type-3: 1 pole at origin (fpI), two zeros (fz1,fz2), two HF poles: f_opto and fp3."""
    import math
    fc = max(p.fc, 1.0)
    fz1 = max(p.fz1, 1.0); fz2 = max(p.fz2, 1.0)
    fp3 = max(getattr(p, "fp3", 3.0*fc), 1.0)
    c1 = max(p.c1_nf*1e-9, 1e-12)
    c2 = max(p.c2_nf*1e-9, 1e-12)
    c3 = max(p.c3_nf*1e-9, 1e-12)

    # Zeros via R2,C1 and R1,C2
    r2 = 1.0/(TWOPI * fz1 * c1)
    r1 = 1.0/(TWOPI * fz2 * c2)

    # HF pole fp3 via R3,C3
    r3_hp = 1.0/(TWOPI * fp3 * c3)

    # Outside gains and opto pole (C2 in parallel with Copto lowers f_opto)
    f_opto = 1.0/(TWOPI * p.r_pullup * (p.copto_nf*1e-9 + c2))
    g2 = (p.r_pullup * p.ctr_min) / max(r_led, 1e-9)
    g_opto = 1.0/_mag_ratio(fc, f_opto)

    # Compose |G_total| at fc and solve fpI
    num  = _mag_ratio(fc, fz1) * _mag_ratio(fc, fz2)
    den_hf = _mag_ratio(fc, fp3)  # f_opto is accounted via g_opto
    gc_target = 10.0**(p.gc_db/20.0)
    g_const = g2 * g_opto * (num / den_hf)
    fpI = max(gc_target * fc / max(g_const, 1e-18), 1.0)

    # Integrator uses C1 as Cint (sizing-wise), get Rint
    c_int = c1
    r_int = 1.0/(TWOPI * fpI * c_int)

    # Round to E24
    r1_e = _e24_round(r1); r2_e = _e24_round(r2); r3i_e = _e24_round(r_int); r3hp_e = _e24_round(r3_hp)
    c1_e = _e24_round(c1, prefer_high=True); c2_e = _e24_round(c2, prefer_high=True); c3_e = _e24_round(c3, prefer_high=True)

    # Effective freqs
    fz1_e = 1.0/(TWOPI*max(r2_e,1e-3)*max(c1_e,1e-15))
    fz2_e = 1.0/(TWOPI*max(r1_e,1e-3)*max(c2_e,1e-15))
    fpI_e = 1.0/(TWOPI*max(r3i_e,1e-3)*max(c1_e,1e-15))
    fp3_e = 1.0/(TWOPI*max(r3hp_e,1e-3)*max(c3_e,1e-15))
    f_opto_e = 1.0/(TWOPI * p.r_pullup * (p.copto_nf*1e-9 + c2_e))

    g_comp = ( _mag_ratio(fc, fz1_e) * _mag_ratio(fc, fz2_e) ) / ( (fc/max(fpI_e,1.0)) * _mag_ratio(fc, fp3_e) )
    g_total = g2 * (1.0/_mag_ratio(fc, f_opto_e)) * g_comp
    g_total_db = 20.0*math.log10(max(g_total,1e-18))

    return {
        "type": "Type-3 (no fast lane)",
        "parts": {
            "R1_Ohm": r1_e, "R2_Ohm": r2_e, "Rint_Ohm": r3i_e, "R3_HP_Ohm": r3hp_e,
            "C1_F": c1_e, "C2_F": c2_e, "C3_F": c3_e
        },
        "freqs": {
            "fz1_Hz": fz1_e, "fz2_Hz": fz2_e,
            "fpI_Hz": fpI_e, "fp3_Hz": fp3_e,
            "f_opto_Hz": f_opto_e
        },
        "gain_at_fc_dB": g_total_db,
    }


def compute_optocoupler(p: InputParams) -> Dict[str, Any]:
    # Divider
    r_up, r_low = _calc_divider(p.v_out, p.v_ref, p.i_div_uA)
    # Decide topology and compute LED path limits according to presence of fast lane
    comp_type = (getattr(p, "comp_type", "type3") or "type3").strip().lower()
    if comp_type in ("type1","type2"):
        # fast lane present – LED referenced to Vout, no zener bias
        r_led_max = _led_r_max_fastlane(p.v_out, p.v_f_led, p.v_ref, p.vdd, p.vce_sat, p.i_bias_mA, p.r_pullup, p.ctr_min)
        if r_led_max <= 0:
            raise ValueError("R_LED,max ≤ 0 — проверьте Vout/Vf/Vref/Vdd/Ibias (fast‑lane).")
        r_led = p.led_margin * r_led_max
        i_collector_min, i_collector_max = _ti_fb_window(p.vdd, p.r_pullup, p.vfb_min, p.vfb_max)
        i_led_req = _i_led_required(i_collector_max, p.ctr_min)
        i_led_avail = max((p.v_out - p.v_ref - p.v_f_led)/max(r_led,1e-9), 0.0)
    else:
        # no fast lane – LED referenced to fixed bias (zener)
        r_led_max = _led_r_max_nofastlane(p.v_bias_zener, p.v_f_led, p.v_ref, p.vdd, p.vce_sat, p.i_bias_mA, p.r_pullup, p.ctr_min)
        if r_led_max <= 0:
            raise ValueError("R_LED,max ≤ 0 — проверьте Vbias/Vf/Vref/Vdd/Ibias (no‑fast‑lane).")
        r_led = p.led_margin * r_led_max
        # TI FB window still defines collector current range
        i_collector_min, i_collector_max = _ti_fb_window(p.vdd, p.r_pullup, p.vfb_min, p.vfb_max)
        i_led_req = _i_led_required(i_collector_max, p.ctr_min)
        i_led_avail = max((p.v_bias_zener - p.v_ref - p.v_f_led)/max(r_led,1e-9), 0.0)
    if comp_type == "type1":
        network = _compute_type1(p, r_led, r_up, r_low)
    elif comp_type == "type2":
        network = _compute_type2(p, r_led, r_up, r_low)
    else:
        network = _compute_type3(p, r_led, r_up, r_low)

    warnings = []
    # conservative f_opto using Copto + C2 (if present)
    f_opto_cons = 1.0/(TWOPI * p.r_pullup * (p.copto_nf*1e-9 + max(p.c2_nf*1e-9,0.0)))
    if p.fc > 0.3 * f_opto_cons:
        warnings.append("fc выше 0.3·f_opto — запас фазы может быть недостаточным.")
    if r_led > r_led_max:
        warnings.append("R_LED выбран выше R_LED,max. Уменьшите R_LED либо увеличьте CTR/уменьшите Rpullup.")
    if i_led_avail < i_led_req:
        warnings.append(f"Недостаточно тока LED в худшем случае окна FB: требуется ≥{i_led_req*1e3:.2f} mA, доступно {i_led_avail*1e3:.2f} mA.")
    if p.i_div_uA < 150:
        warnings.append("Ток делителя TL431 <150 µA — точность TL431 может деградировать.")
    if p.ctr_min < 0.2:
        warnings.append("CTR(min) выглядит заниженным — перепроверьте даташит/рабочую точку.")

    # Build report
    lines = []
    lines.append(f"=== TL431 + Optocoupler — {network['type']} ===")
    lines.append("— Исходные:")
    lines.append(f"  Vout={p.v_out:.3g} V, Vdd={p.vdd:.3g} V, Rpullup={p.r_pullup:.0f} Ω, CTR(min)={p.ctr_min:.3g}, Copto={p.copto_nf:.3g} nF")
    lines.append(f"  TL431: Vref={p.v_ref:.3g} V, Idiv≈{p.i_div_uA:.0f} µA → R1≈{r_up:.0f} Ω, Rlower≈{r_low:.0f} Ω")
    lines.append(f"  FB окно: VFB_min={p.vfb_min:.3g} V, VFB_max={p.vfb_max:.3g} V")
    lines.append(f"  R_LED,max≈{r_led_max:.0f} Ω, выбран R_LED≈{r_led:.0f} Ω, I_LED,avail≈{i_led_avail*1e3:.2f} mA")
    lines.append("— Компенсатор:")
    for k,v in network["parts"].items():
        unit = "Ω" if "R" in k else "F"
        lines.append(f"  {k.replace('_',' ')} = {v:.6g} {unit}")
    lines.append("— Частоты:")
    for k,v in network["freqs"].items():
        lines.append(f"  {k} = {v:.3g} Hz")
    lines.append(f"— |G_total(fc)| ≈ {network['gain_at_fc_dB']:.2f} dB  (цель: {p.gc_db:.2f} dB)")

    report_text = "\n".join(lines)
    out = {
        "inputs": { "CompType": comp_type, "VFB_min_V": p.vfb_min, "VFB_max_V": p.vfb_max },
        "network": network,
        "divider": {"R1_Ohm": r_up, "Rlower_Ohm": r_low},
        "bias": {"R_LED_max_Ohm": r_led_max, "R_LED_sel_Ohm": r_led, "I_LED_avail_A": i_led_avail, "I_LED_req_A": i_led_req},
        "warnings": warnings,
        "report_text": report_text,
    }
    return out
