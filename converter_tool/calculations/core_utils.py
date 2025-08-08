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
