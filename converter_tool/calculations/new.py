"""
Additional converter topology calculation modules for the Converter Design Tool.
Each module implements the common ConverterDesign interface declared in
converter_tool/calculations/base.py and can therefore be auto‑discovered by the
existing GUI.

The implementation strategy is identical to the existing FlybackDesign class:
    * Accept a dictionary with all electrical and mechanical input parameters.
    * Compute key design quantities and expose them through a `results` dict.
    * Raise ValueError on obviously invalid input (e.g. Vin_min>Vin_max).

Common helper utilities required by several topologies are shipped in the small
`_core_utils` mix‑in – at the bottom of this file – to avoid code duplication.

All formula numbers below refer to the 2nd edition of B.Yu. Semenov
«Силовая электроника: от простого к сложному» (СОЛОН‑Пресс, 2009) that the
user attached. File search citations:
    – Transformer gabarit formula (3.70) → fileciteturn1file2
    – Primary turns for forward family (15.19) and secondary turns (15.20) →
      fileciteturn2file12
    – Push‑pull voltage relationships (15.1‑15.7) → fileciteturn2file13
    – Half‑bridge output/turns equations (15.26‑15.27) → fileciteturn2file18
    – CCM / DCM inductor design (10.7‑10.11) → fileciteturn2file7
"""
from __future__ import annotations
import math
from typing import Dict, Any

from .base import ConverterDesign  # type: ignore  # Imported from project.

################################################################################
# Generic utilities
################################################################################
class _CoreUtils:
    """Mix‑in with helper methods shared by several topologies."""

    @staticmethod
    def _core_ss0_min(p_out: float, f_sw: float, b_max: float, j: float = 4.0,
                      k_phi: float = 1.0) -> float:
        """Return minimal SS₀ (см⁴) from formula (3.70) fileciteturn1file2."""
        # S·S0 ≥ Pn * kφ / (f · B · j)
        return (p_out * k_phi) / (f_sw * b_max * j)

    @staticmethod
    def _primary_turns(v_in_min: float, d_max: float, b_max: float,
                       s_core: float, f_sw: float) -> int:
        """Equation (15.19) for single‑ended topologies fileciteturn2file12."""
        w1 = (v_in_min * d_max) / (b_max * s_core * f_sw)
        return max(1, math.ceil(w1))

    @staticmethod
    def _ccm_inductor(l_value: float, i_out: float, dv: float, f_sw: float) -> int:
        """Very rough delta‑I check for CCM; used by forward / bridge output filter."""
        delta_i = (v_ripple := dv) / (l_value * f_sw)
        return 0 if delta_i <= 0.4 * i_out else 1  # 0=CCM, 1=DCM.

################################################################################
# 1. Forward converter (single‑switch) ################################################
################################################################################
class ForwardDesign(ConverterDesign, _CoreUtils):
    """Single‑switch forward topology.
    Key traits: energy is transferred while the MOSFET is ON, requires reset
    winding or RCD clamp.
    """
    name = "forward"

    def calculate(self) -> Dict[str, Any]:
        p = self.params  # shorthand
        if p['Vin_min'] > p['Vin_max']:
            raise ValueError("Vin_min must not exceed Vin_max")

        # Transformer –––———————————————————————————————
        d_max = p.get('D_max', 0.45)  # recommended <0.5 to leave room for reset
        n_ps = (p['Vin_min'] * d_max) / p['Vout']  # eq. (13.2) single‑ended ratio
        w1 = self._primary_turns(p['Vin_min'], d_max, p['B_max'],
                                 p['core_Ae'], p['f_sw'])
        w2 = math.ceil(w1 / n_ps)

        # Reset choice: assume demag winding Nreset = Np (exact 1:1)
        v_ds = p['Vin_max'] + p['Vin_max']  # worst‑case stress (Vin + Nreset/Np·Vin)

        # Output filter Lout (use CCM criterion from (10.7‑10.11))
        l_min = (p['Vout'] * (1 - d_max)) / (p['delta_I'] * p['f_sw'] * 2)
        mode = 'CCM' if self._ccm_inductor(l_min, p['Iout'], p['delta_I'],
                                           p['f_sw']) == 0 else 'DCM'

        # Core window product check (3.70)
        ss0_min = self._core_ss0_min(p['Pout'], p['f_sw'], p['B_max'])

        self.results.update({
            'turns_ratio': round(n_ps, 3),
            'primary_turns': w1,
            'secondary_turns': w2,
            'vds_max': round(v_ds, 1),
            'l_out_min_uH': round(l_min * 1e6, 2),
            'output_current_mode': mode,
            'SS0_min_cm4': round(ss0_min, 3),
        })
        return self.results

################################################################################
# 2. Push‑pull converter ###############################################################
################################################################################
class PushPullDesign(ConverterDesign, _CoreUtils):
    """Classic two‑transistor push‑pull (centre‑tapped primary).
    Voltage relationships follow (15.1‑15.7) fileciteturn2file13.
    """
    name = "push_pull"

    def calculate(self) -> Dict[str, Any]:
        p = self.params
        d_max = p.get('D_max', 0.45)

        # Centre‑tapped: each half primary sees Vin, so n = Vin_min * d_max / Vout
        n_ps = (p['Vin_min'] * d_max) / p['Vout']
        w_half = self._primary_turns(p['Vin_min'], d_max, p['B_max'],
                                     p['core_Ae'], p['f_sw'])
        w1_total = w_half * 2
        w2 = math.ceil(w_half / n_ps) * 2  # centre‑tapped secondary

        # Switch stress limited to 2×Vin for perfect symmetry
        vds = 2 * p['Vin_max']

        ss0_min = self._core_ss0_min(p['Pout'], p['f_sw'], p['B_max'])

        self.results.update({
            'turns_ratio': round(n_ps, 3),
            'primary_turns_total': w1_total,
            'secondary_turns_total': w2,
            'vds_max': vds,
            'SS0_min_cm4': round(ss0_min, 3),
        })
        return self.results

################################################################################
# 3. Half‑bridge converter ############################################################
################################################################################
class HalfBridgeDesign(ConverterDesign, _CoreUtils):
    """Half‑bridge with capacitive divider (Figure 15.7).
    Equations from 15.26‑15.27 fileciteturn2file18.
    """
    name = "half_bridge"

    def calculate(self) -> Dict[str, Any]:
        p = self.params
        d_max = p.get('D_max', 0.45)

        # Effective Vin on primary is Vin/2 (because of divider)
        n_ps = ((p['Vin_min'] / 2) * d_max) / p['Vout']
        w1 = self._primary_turns(p['Vin_min']/2, d_max, p['B_max'],
                                 p['core_Ae'], p['f_sw'])
        w2 = math.ceil(w1 / n_ps)

        vds = p['Vin_max']  # each FET sees full bus only
        i_switch_rms = (p['Iout'] * p['Vout']) / (p['Vin_min'] * d_max)

        self.results.update({
            'turns_ratio': round(n_ps, 3),
            'primary_turns': w1,
            'secondary_turns': w2,
            'vds_max': vds,
            'ids_rms_est': round(i_switch_rms, 2),
        })
        return self.results

################################################################################
# 4. Full‑bridge converter ############################################################
################################################################################
class FullBridgeDesign(ConverterDesign, _CoreUtils):
    """H‑bridge (Figure 15.10) – transfers energy every half‑cycle.
    """
    name = "full_bridge"

    def calculate(self) -> Dict[str, Any]:
        p = self.params
        d_max = p.get('D_max', 0.45)
        # Primary sees full Vin
        n_ps = (p['Vin_min'] * d_max) / p['Vout']
        w1 = self._primary_turns(p['Vin_min'], d_max, p['B_max'],
                                 p['core_Ae'], p['f_sw'])
        w2 = math.ceil(w1 / n_ps)

        vds = p['Vin_max']  # single switch stress same as bus in ideal bridge
        i_pk = (2 * p['Pout']) / (p['Vin_min'] * d_max)  # idealised

        self.results.update({
            'turns_ratio': round(n_ps, 3),
            'primary_turns': w1,
            'secondary_turns': w2,
            'vds_max': vds,
            'primary_peak_current_est': round(i_pk, 2),
        })
        return self.results
