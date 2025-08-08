#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Two-switch Flyback converter design tool (classic 2T, hard-switched; DCM-oriented)
- Reuses the proven flyback calculation pipeline for magnetics, windings and caps
- Adjusts device stresses and losses for two MOSFETs and clamp behavior
- Optionally enforces D<0.5 for classic 2T operation
References used in formulas are documented in README and UI help.
"""

from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
import math

# Reuse types and helpers from single-switch flyback calculator
from .flyback_design import (
    FlybackInput, OutputSpec, CoreParameters, Geometry, Steinmetz, MosfetParams, RCDClamp,
    InitialDesign, RefinedDesign,
    normalize_cfg, estimate_initial_design, refine_with_core as refine_single,
    sweep_k as sweep_single,
    DEFAULT_CORELIB, load_core_library
)

# --- Specializations for two-switch flyback ---

@dataclass
class TwoSwitchInput(FlybackInput):
    """Same fields as FlybackInput. Additional control flags below."""
    force_dcm: bool = True          # two-switch design in this tool is DCM-first
    duty_max: float = 0.45          # in classic 2T keep below 0.5
    soft_switch: bool = False       # placeholder for regenerative soft-switch topology (future)
    vds_overhead: float = 1.25      # design margin on Vds

def _refine_two_switch(fin: TwoSwitchInput, geom: Geometry, core: CoreParameters,
                       ini: InitialDesign, outputs: List[OutputSpec],
                       stein: Optional[Steinmetz]=None,
                       mosfet: Optional[MosfetParams]=None) -> RefinedDesign:
    """Wrap single-switch refinement to reuse magnetics and replace stresses/losses for 2T."""
    # Get the same refined magnetic design from single-switch path
    ref = refine_single(fin, geom, core, ini, outputs, rcd=None, stein=stein, mosfet=None, force_dcm=fin.force_dcm)

    # --- Replace device stresses for the 2T topology ---
    # Classic two-switch flyback clamps primary to Vin at turn-off -> each MOSFET sees ~Vin
    vds_ideal = float(fin.vin_max)
    vds_required = vds_ideal * fin.vds_overhead

    # Secondary diode VRRM remains approximately the same relationship
    diode_vrrm_required_each = {}
    for name, ns in ref.ns_turns.items():
        o = next(o for o in outputs if o.name == name)
        k_i = ref.np_turns / ns
        diode_vrrm_required_each[name] = fin.vin_max / k_i + o.v + o.diode_drop

    # --- Losses recomputed for two MOSFETs ---
    losses = dict(ref.losses) if isinstance(ref.losses, dict) else {}
    P_mos_cond = 0.0; P_sw = 0.0; P_coss = 0.0; P_gate = 0.0
    if mosfet is not None:
        # Temperature-adjusted Rds(on)
        Rds = (mosfet.rds_on_mohm * 1e-3) * (1.0 + mosfet.rds_temp_coeff * (mosfet.rds_temp_C - 25.0))
        # Two series MOSFETs carry the same primary current during Ton
        Irms = ref.irms_pri_new_A
        P_mos_cond = 2.0 * (Irms**2) * Rds
        # Turn-on/off overlap loss (hard-switch approximation)
        tr = mosfet.tr_ns * 1e-9; tf = mosfet.tf_ns * 1e-9
        if fin.soft_switch:
            P_sw = 0.0  # ZVS assumed in improved 2T
        else:
            P_sw = 2.0 * 0.5 * vds_required * ref.ipk_new_A * (tr + tf) * fin.fsw * mosfet.k_sw_overlap
        # Coss loss (approximate; energy recovered by clamp is neglected in this estimate)
        Coss = (mosfet.coss_pF * 1e-12) if getattr(mosfet, 'coss_pF', None) not in (None,0) else (mosfet.coss_nF * 1e-9)
        if fin.soft_switch:
            P_coss = 0.0  # regenerative clamp assumed to recover Coss energy
        else:
            P_coss = 2.0 * 0.5 * Coss * (vds_required**2) * fin.fsw
        # Gate drive
        Qg = mosfet.qg_nC * 1e-9
        P_gate = 2.0 * Qg * mosfet.vgate_V * fin.fsw
        losses.update(dict(Pmos_cond_W=P_mos_cond, Pmos_sw_W=P_sw, Pmos_coss_W=P_coss, Pgate_W=P_gate,
                           Pmos_total_W=(P_mos_cond+P_sw+P_coss+P_gate)))

    # Rebuild eta estimate
    Pout = sum(o.v*o.i for o in outputs) * fin.overload
    P_losses_known = 0.0
    for k,v in losses.items():
        if isinstance(v, (int, float)) and k.endswith("_W"):
            P_losses_known += float(v)
    eta_est = max(0.0, min(0.999, Pout / max(1e-9, (Pout + P_losses_known))))
    losses["Ptotal_W"] = P_losses_known
    losses["eta_est"] = eta_est
    losses["soft_switch_mode"] = bool(fin.soft_switch)

    # Replace stresses in the result
    ref.vds_ideal_V = vds_ideal
    ref.vds_with_overhead_V = vds_required
    ref.diode_vrrm_required_each_V = diode_vrrm_required_each
    ref.losses = losses
    return ref

def run(cfg: Dict[str, Any], corelib: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Entry point compatible with GUI."""
    cfg = normalize_cfg(cfg)
    fin = TwoSwitchInput(**cfg["input"])
    outs = [OutputSpec(**o) for o in cfg["outputs"]]
    vref_override = cfg.get("vref_override", None)
    # Limit duty_max to < 0.5 for classic two-switch
    if fin.soft_switch:
        fin.duty_max = min(0.8, max(0.5, fin.duty_max))
    else:
        if fin.duty_max >= 0.5:
            fin.duty_max = 0.49

    ini = estimate_initial_design(fin, outs, vref_override=vref_override)
    res = {"input": asdict(fin), "outputs":[asdict(o) for o in outs], "initial": asdict(ini)}

    if "core" in cfg and "geometry" in cfg:
        core = CoreParameters(**cfg["core"])
        geom = Geometry(**cfg["geometry"])
        stein = Steinmetz(**cfg["steinmetz"]) if "steinmetz" in cfg else None
        mosfet = MosfetParams(**cfg["mosfet"]) if "mosfet" in cfg else None

        # Optional K-optimizer (using single-switch sweep for magnetics; stresses corrected thereafter)
        if cfg.get("k_optimize"):
            kcfg = cfg["k_optimize"]
            crit = kcfg.get("criterion","min_vds")
            dmin = float(kcfg.get("dmin",0.2)); dmax=float(kcfg.get("dmax",0.45)); dstep=float(kcfg.get("dstep",0.02))
            # reuse sweep grid but clamp dmax
            dmax = min(dmax, 0.49)
            best = None
            grid = []
            for D in [dmin + i*dstep for i in range(int((dmax-dmin)/dstep)+1)]:
                vref = (D/(1.0-D)) * fin.vin_min
                ini_i = estimate_initial_design(fin, outs, vref_override=vref)
                ref_i = _refine_two_switch(fin, geom, core, ini_i, outs, stein=stein, mosfet=mosfet)
                metric = None
                if crit=="min_vds":
                    metric = ref_i.vds_with_overhead_V
                elif crit=="min_ipk":
                    metric = ref_i.ipk_new_A
                elif crit=="min_vrrm":
                    metric = max(ref_i.diode_vrrm_required_each_V.values())
                elif crit=="min_loss":
                    metric = ref_i.losses.get("Ptotal_W", float("inf"))
                else:
                    metric = ref_i.vds_with_overhead_V
                grid.append({"D": D, "metric": metric})
                if best is None or metric < best["metric"]:
                    best = {"D": D, "metric": metric, "ini": ini_i, "ref": ref_i}
            res["k_sweep"] = {"criterion": crit, "best": {"D": best["D"], "metric": best["metric"]}, "grid_len": len(grid)}
            ini = best["ini"]
            ref = best["ref"]
            res["initial"] = asdict(ini)
            res["refined"] = asdict(ref)
        else:
            ref = _refine_two_switch(fin, geom, core, ini, outs, stein=stein, mosfet=mosfet)
            res["refined"] = asdict(ref)

        # Ratings / warnings
        if mosfet is not None and hasattr(mosfet, "vds_V"):
            margin = mosfet.vds_V / ref.vds_with_overhead_V if ref.vds_with_overhead_V else float("inf")
            res.setdefault("ratings", {})["mosfet_vds_margin"] = margin
            if margin < 1.0 - 1e-6:
                res.setdefault("warnings", []).append(
                    f"MOSFET Vds {mosfet.vds_V:.0f} V < required {ref.vds_with_overhead_V:.0f} V"
                )
        # Fill factor warning (reuse from single-switch)
        if ref.fill_factor and ref.fill_factor > 0.5:
            res.setdefault("warnings", []).append(f"Fill factor {ref.fill_factor:.2f} is high; check winding window.")

    return res

# -- Class wrapper for GUI --
class TwoSwitchFlybackDesign:
    normalize_cfg = staticmethod(normalize_cfg)
    load_core_library = staticmethod(load_core_library)
    DEFAULT_CORELIB = DEFAULT_CORELIB

    def run_calculation(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return run(cfg, corelib=self.load_core_library(self.DEFAULT_CORELIB) if self.DEFAULT_CORELIB else None)

if __name__ == "__main__":
    import json, argparse, os
    p = argparse.ArgumentParser(description="Two-Switch Flyback design tool")
    p.add_argument("--config", type=str, help="JSON config file")
    args = p.parse_args()
    if not args.config:
        raise SystemExit("Provide --config JSON")
    cfg = json.load(open(args.config, "r", encoding="utf-8"))
    res = run(cfg)
    print(json.dumps(res, ensure_ascii=False, indent=2))
