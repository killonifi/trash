#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flyback converter design tool (v12, DCM)
- K (Np/Ns) optimizer by criterion (min Vds, min Ipk, min max-VRRM, min total losses)
- Core library support (JSON), returned for GUI consumption
- Multi-outputs; losses: copper, core (Steinmetz), MOSFET, diodes; clamp (RCD)
"""
import json, math, sys, os
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Any

MU0 = 4*math.pi*1e-7
RHO_CU_20 = 1.724e-8
ALPHA_CU = 0.00393
FERRITE_RHO_KG_PER_M3 = 4800.0

def parse_num(s):
    if isinstance(s, (int, float)): return float(s)
    if s is None or (isinstance(s,str) and s.strip()==""): return 0.0
    s = str(s).strip().replace(",", ".")
    import re
    m = re.match(r'^([+-]?\d+(?:\.\d+)?)([eE][+-]?\d+)?\s*([GMkmunpµ]?)', s)
    if not m: raise ValueError(f"Cannot parse number: {s}")
    base = float(m.group(1) + (m.group(2) or ""))
    suf = (m.group(3) or "").replace("µ","u")
    mult = {"G":1e9,"M":1e6,"k":1e3,"":1.0,"m":1e-3,"u":1e-6,"n":1e-9,"p":1e-12}
    if suf not in mult: raise ValueError(f"Bad suffix in {s}")
    return base * mult[suf]

def rho_cu_at(Tc: float) -> float:
    return RHO_CU_20 * (1.0 + ALPHA_CU * (Tc - 20.0))

def steinmetz_ki(k: float, alpha: float, beta: float) -> float:
    """Calculate ki from classic Steinmetz coefficients.

    Based on the iGSE formulation in \[1].
    """
    x = (beta - alpha + 1.0) / 2.0
    y = (alpha + 1.0) / 2.0
    integral = 2.0 * math.gamma(x) * math.gamma(y) / math.gamma(x + y)
    return k / ((2.0 * math.pi) ** (alpha - 1.0) * integral)

# Simple AWG table: (gauge, area_mm2)
AWG_TABLE = [
    (10, 5.26), (11, 4.17), (12, 3.31), (13, 2.62), (14, 2.08),
    (15, 1.65), (16, 1.31), (17, 1.04), (18, 0.823), (19, 0.653),
    (20, 0.519), (21, 0.412), (22, 0.326), (23, 0.258), (24, 0.205),
    (25, 0.162), (26, 0.129), (27, 0.102), (28, 0.0810), (29, 0.0642),
    (30, 0.0509), (31, 0.0404), (32, 0.0320), (33, 0.0254), (34, 0.0201),
    (35, 0.0160), (36, 0.0127), (37, 0.0100), (38, 0.00797),
    (39, 0.00632), (40, 0.0050)
]

def select_awg(area_req: float, delta_mm: Optional[float] = None,
               max_parallel: int = 5) -> Dict[str, float]:
    """Pick an AWG size and number of parallels so total area ≥ ``area_req``.

    If ``delta_mm`` is given the function first searches gauges whose individual
    strand diameter is **strictly** less than ``2*delta_mm`` while using no more
    than ``max_parallel`` parallels (default 5). If no such combination can
    provide the required copper area, the skin‑depth constraint is dropped and
    the best match is chosen from the full AWG table, still observing the
    ``max_parallel`` limit.
    """

    def find_best(table):
        for gauge, area in reversed(table):  # iterate from thinnest to thickest
            n = math.ceil(area_req / area)
            if n <= max_parallel:
                total = n * area
                return gauge, area, n, total
        return None

    if delta_mm is not None:
        limit = 2.0 * delta_mm
        table_skin = [
            (g, a) for g, a in AWG_TABLE
            if math.sqrt(4.0 * a / math.pi) < limit
        ]
        best = find_best(table_skin)
        if best is not None:
            gauge, area, n, total = best
            return {"awg": f"AWG{gauge}", "awg_area_mm2": area,
                    "parallel": n, "total_area_mm2": total}

    best = find_best(AWG_TABLE)
    if best is None:
        gauge, area = AWG_TABLE[0]
        n = max_parallel
        total = n * area
        best = (gauge, area, n, total)

    gauge, area, n, total = best
    return {"awg": f"AWG{gauge}", "awg_area_mm2": area, "parallel": n, "total_area_mm2": total}

@dataclass
class OutputSpec:
    name: str
    v: float
    i: float
    ripple_v: float = 0.02
    diode_drop: float = 0.5
    mlt_mm: Optional[float] = None
    qrr_nC: Optional[float] = None
def __post_init__(self):
    """Ensure all numeric fields are floats; accept suffixes k, m, u etc."""
    self.v = parse_num(self.v)
    self.i = parse_num(self.i)
    self.ripple_v = parse_num(self.ripple_v)
    self.diode_drop = parse_num(self.diode_drop)
    # optional fields
    if self.mlt_mm is not None and self.mlt_mm != "":
        self.mlt_mm = parse_num(self.mlt_mm)
    if self.qrr_nC is None or self.qrr_nC == "":
        self.qrr_nC = 0.0
    else:
        self.qrr_nC = parse_num(self.qrr_nC)
@dataclass
class FlybackInput:
    vin_min: float
    vin_max: float
    fsw: float
    duty_max: float = 0.45
    eff: float = 0.88
    input_type: str = "dc"
    f_line: float = 50.0
    overload: float = 1.2
    main_output: str = ""
    force_dcm: bool = False

@dataclass
class Geometry:
    jmax_A_per_mm2: float = 4.0
    mlt_pri_mm: float = 40.0
    mlt_sec_default_mm: float = 40.0
    window_area_mm2: Optional[float] = None
    copper_temp_C: float = 60.0
    ac_factor_pri: float = 1.5
    ac_factor_sec: float = 1.5

@dataclass
class CoreParameters:
    ae_mm2: float
    le_mm: float
    bmax_T: float = 0.20
    al_nH_per_turn2: Optional[float] = None
    core_volume_mm3: Optional[float] = None
    name: Optional[str] = None

@dataclass
class Steinmetz:
    k: float
    alpha: float
    beta: float
    k_unit: str = "W/m3"
    rho_kg_per_m3: float = FERRITE_RHO_KG_PER_M3
    ki: float = field(init=False)

    def __post_init__(self):
        if self.k_unit.lower() in ("w/kg", "w_per_kg"):
            self.k *= self.rho_kg_per_m3
            self.k_unit = "W/m3"
        self.ki = steinmetz_ki(self.k, self.alpha, self.beta)

@dataclass
class MosfetParams:
    rds_on_mohm: float = 150.0
    rds_temp_C: float = 100.0
    rds_temp_coeff: float = 0.004
    tr_ns: float = 30.0
    tf_ns: float = 30.0
    coss_nF: float = 2.0
    coss_pF: Optional[float] = None
    qg_nC: float = 40.0
    vgate_V: float = 10.0
    k_sw_overlap: float = 1.0

@dataclass
class RCDClamp:
    enable: bool = True
    leakage_frac: float = 0.015
    vclamp_target_V: Optional[float] = None
    ripple_frac: float = 0.1
    return_to_bus: bool = True
    margin: float = 0.1

@dataclass
class InitialDesign:
    pout_total_W: float
    lm_target_H: float
    ipk_A: float
    irms_pri_A: float
    d_used: float
    d_vin_min: float
    d_vin_max: float
    k_np_over_ns: float
    vref_V: float
    vds_ideal_max_V: float
    diode_vrrm_primary_V: float
    cout_min_each_F: Dict[str, float]
    cin_min_F: float
    per_output: Dict[str, Dict[str, float]]

@dataclass
class RefinedDesign:
    np_turns: int
    ns_turns: Dict[str, int]
    k_actual_np_over_ns_main: float
    gap_m: float
    lm_actual_H: float
    ipk_new_A: float
    irms_pri_new_A: float
    dcm_ok_main: bool
    t_off_main_s: float
    lsec_main_H: float
    delta_B_T: float
    wires: Dict[str, Any]
    vds_ideal_V: float
    vds_with_overhead_V: float
    diode_vrrm_ideal_each_V: Dict[str, float]
    diode_vrrm_required_each_V: Dict[str, float]
    fill_factor: Optional[float]
    rcd: Optional[Dict[str, Any]]
    core_loss_W: Optional[float]
    losses: Dict[str, Any]
    notes: Dict[str, Any]

# ----- computations -----

def estimate_duty(vref: float, vin: float) -> float:
    return vref / (vin + vref)

def estimate_initial_design(fin: FlybackInput, outputs: List[OutputSpec], cin_vrip: float = 5.0, vref_override: Optional[float]=None) -> InitialDesign:
    pout = sum(o.v * o.i for o in outputs)
    pout_worst = pout * fin.overload
    main_name = fin.main_output or outputs[0].name
    main = next(o for o in outputs if o.name == main_name)

    if vref_override is not None:
        vref = vref_override
    else:
        vref = (fin.duty_max/(1.0-fin.duty_max)) * fin.vin_min

    k_np_over_ns = vref / (main.v + main.diode_drop)
    dmin = estimate_duty(vref, fin.vin_min)

    lm_target = (fin.vin_min**2 * dmin**2 * fin.eff) / (2.0 * pout_worst * fin.fsw)
    ipk = (fin.vin_min * dmin) / (lm_target * fin.fsw)
    irms_pri = ipk * (dmin/3.0) ** 0.5
    vds_ideal = fin.vin_max + k_np_over_ns * (main.v + main.diode_drop)

    diode_vrrm_each, cout_each, per_out = {}, {}, {}
    for o in outputs:
        k_i = vref / (o.v + o.diode_drop)
        diode_vrrm_each[o.name] = fin.vin_max / k_i + o.v
        # Cout ≈ Iout*(1-D)/(2*ΔV*f_sw) for DCM flyback
        cout_each[o.name] = (o.i * (1.0 - dmin)) / (2.0 * max(1e-6, o.ripple_v) * fin.fsw)
        per_out[o.name] = {"k_np_over_ns_ideal": k_i, "cout_min_F": cout_each[o.name], "diode_vrrm_ideal_V": diode_vrrm_each[o.name]}

    if fin.input_type.lower() == "dc":
        iin = pout / (fin.eff * fin.vin_min)
        cin_min = iin * dmin / (max(1e-6, cin_vrip) * fin.fsw)
    else:
        cin_min = pout / (fin.eff * max(1e-3, cin_vrip) * 2.0 * fin.f_line)

    d_vin_min = dmin
    d_vin_max = estimate_duty(vref, fin.vin_max)

    return InitialDesign(
        pout_total_W=pout, lm_target_H=lm_target, ipk_A=ipk, irms_pri_A=irms_pri,
        d_used=fin.duty_max, d_vin_min=d_vin_min, d_vin_max=d_vin_max,
        k_np_over_ns=k_np_over_ns, vref_V=vref, vds_ideal_max_V=vds_ideal,
        diode_vrrm_primary_V=diode_vrrm_each[main_name],
        cout_min_each_F=cout_each, cin_min_F=cin_min, per_output=per_out
    )

def skin_depth_mm(f_hz: float) -> float:
    return 1e3 * (2.0 * RHO_CU_20 / (2.0 * math.pi * f_hz * MU0)) ** 0.5

def refine_with_core(fin: FlybackInput, geom: Geometry, core: CoreParameters,
                     ini: InitialDesign, outputs: List[OutputSpec],
                     rcd: Optional[RCDClamp]=None,
                     stein: Optional[Steinmetz]=None,
                     mosfet: Optional[MosfetParams]=None,
                     force_dcm: bool=False) -> RefinedDesign:
    Ae = core.ae_mm2 * 1e-6
    Duse = ini.d_vin_min
    np_min = math.ceil((fin.vin_max * Duse) / (core.bmax_T * Ae * fin.fsw))
    np_turns = int(np_min)

    main_name = fin.main_output or outputs[0].name
    main = next(o for o in outputs if o.name == main_name)

    period = 1.0 / fin.fsw
    while True:
        ns_turns: Dict[str,int] = {}
        for o in outputs:
            k_ideal = ini.per_output[o.name]["k_np_over_ns_ideal"]
            ns_turns[o.name] = max(1, int(round(np_turns / max(k_ideal, 1e-12))))

        k_act = np_turns / ns_turns[main_name]
        gap = MU0 * (np_turns**2) * Ae / max(ini.lm_target_H, 1e-18)
        lm_actual = MU0 * (np_turns**2) * Ae / gap
        ipk = (fin.vin_min * ini.d_vin_min) / (lm_actual * fin.fsw)
        irms_pri = ipk * (ini.d_vin_min/3.0) ** 0.5
        lsec_main = lm_actual * (ns_turns[main_name]/np_turns)**2
        ipk_sec_main = ipk * k_act
        toff = lsec_main * ipk_sec_main / (main.v + main.diode_drop)
        dcm_ok = toff <= (1.0 - ini.d_vin_min) * period + 1e-15
        if not force_dcm or dcm_ok or np_turns>1000:
            break
        np_turns += 1

    # Flux swing (ΔB)
    dB = (fin.vin_max * ini.d_vin_min) / (np_turns * Ae * fin.fsw)

    # Wires with AWG selection
    delta = skin_depth_mm(fin.fsw)
    wires: Dict[str, Dict[str,float]] = {}
    area_pri = irms_pri * fin.overload * geom.ac_factor_pri / geom.jmax_A_per_mm2
    sel_pri = select_awg(area_pri, delta)
    wires["primary_area_mm2"] = area_pri
    wires["primary_awg"] = sel_pri["awg"]
    wires["primary_awg_area_mm2"] = sel_pri["awg_area_mm2"]
    wires["primary_parallel"] = sel_pri["parallel"]
    wires["primary_total_area_mm2"] = sel_pri["total_area_mm2"]
    wires["skin_depth_mm"] = delta

    irms_sec_map: Dict[str,float] = {}
    for o in outputs:
        k_i = np_turns / ns_turns[o.name]
        ipk_sec = ipk * k_i
        toff_i = min((2.0 * o.i * period) / max(1e-12, ipk_sec),
                      (1.0 - ini.d_vin_min) * period)
        duty_i = toff_i / period
        irms_sec = ipk_sec * math.sqrt(duty_i/3.0)
        irms_sec_map[o.name] = irms_sec
        area_sec = o.i * fin.overload * geom.ac_factor_sec / geom.jmax_A_per_mm2
        sel = select_awg(area_sec, delta)
        wires[f"{o.name}_area_mm2"] = area_sec
        wires[f"{o.name}_awg"] = sel["awg"]
        wires[f"{o.name}_awg_area_mm2"] = sel["awg_area_mm2"]
        wires[f"{o.name}_parallel"] = sel["parallel"]
        wires[f"{o.name}_total_area_mm2"] = sel["total_area_mm2"]

    # Voltages and clamp
    vds_ideal = fin.vin_max + k_act * (main.v + main.diode_drop)
    vds_over = 1.25
    diode_vrrm_ideal_each, diode_vrrm_required_each = {}, {}
    for o in outputs:
        k_i = np_turns / ns_turns[o.name]
        vrrm = fin.vin_max / k_i + o.v
        diode_vrrm_ideal_each[o.name] = vrrm
        diode_vrrm_required_each[o.name] = vrrm

    rcd_info = None
    if rcd and rcd.enable:
        Llk = ini.lm_target_H * rcd.leakage_frac
        E_lk = 0.5 * Llk * ipk**2
        P_lk = E_lk * fin.fsw
        vclamp = rcd.vclamp_target_V or (1.2 * vds_ideal)
        dVc = vclamp * max(0.01, min(0.5, rcd.ripple_frac))
        Cc = E_lk / (vclamp * dVc)
        V_R = vclamp - fin.vin_max if rcd.return_to_bus else vclamp
        R = (V_R**2) / (P_lk * (1.0 + rcd.margin) + 1e-12)
        tau = R * Cc
        rcd_info = dict(Llk_H=Llk, E_lk_J=E_lk, P_lk_W=P_lk, Vclamp_V=vclamp, C_snub_F=Cc, R_snub_Ohm=R, tau_s=tau)
        vds_over = max(1.0, vclamp / max(1e-12, vds_ideal))
    vds_required = vds_ideal * vds_over

    # Fill factor
    fill_factor = None
    if geom.window_area_mm2:
        total_cu = wires["primary_total_area_mm2"] + sum(wires[f"{o.name}_total_area_mm2"] for o in outputs)
        fill_factor = 1.2 * total_cu / geom.window_area_mm2

    # Losses
    losses: Dict[str, Any] = {}
    def rho_cu_at(Tc: float) -> float:
        return RHO_CU_20 * (1.0 + ALPHA_CU * (Tc - 20.0))
    rho = rho_cu_at(geom.copper_temp_C)
    l_pri_m = (geom.mlt_pri_mm * 1e-3) * np_turns
    A_pri_m2 = wires["primary_total_area_mm2"] * 1e-6
    Rdc_pri = rho * l_pri_m / max(1e-12, A_pri_m2)
    Pcu_pri = (irms_pri**2) * Rdc_pri * geom.ac_factor_pri
    losses["Rdc_pri_Ohm"] = Rdc_pri
    losses["Pcu_pri_W"] = Pcu_pri

    Pcu_secs = {}
    for o in outputs:
        ns = ns_turns[o.name]
        l_sec_m = ((o.mlt_mm if o.mlt_mm else geom.mlt_sec_default_mm) * 1e-3) * ns
        A_sec_m2 = wires[f"{o.name}_total_area_mm2"] * 1e-6
        Rdc_sec = rho * l_sec_m / max(1e-12, A_sec_m2)
        irms_sec = irms_sec_map[o.name]
        Pcu_sec = (irms_sec**2) * Rdc_sec * geom.ac_factor_sec
        Pcu_secs[o.name] = {"Rdc_Ohm": Rdc_sec, "Pcu_W": Pcu_sec}
    losses["Pcu_secs"] = Pcu_secs

    p_core_W = None
    if core.core_volume_mm3 and stein:
        vol_m3 = core.core_volume_mm3 * 1e-9
        ton = ini.d_vin_min * period
        tdemag = toff
        slope_on = fin.vin_max / (np_turns * Ae)
        v_off_pri = (main.v + main.diode_drop) * k_act
        slope_off = v_off_pri / (np_turns * Ae)
        deltaB = dB
        term = (abs(slope_on) ** stein.alpha) * ton + (abs(slope_off) ** stein.alpha) * tdemag
        Pv = stein.ki * (deltaB ** (stein.beta - stein.alpha)) * term / period
        p_core_W = Pv * vol_m3
        losses["Pcore_W"] = p_core_W

    P_mos_cond = 0.0; P_sw = 0.0; P_coss = 0.0; P_gate = 0.0
    if mosfet:
        Rds = (mosfet.rds_on_mohm * 1e-3) * (1.0 + mosfet.rds_temp_coeff * (mosfet.rds_temp_C - 25.0))
        P_mos_cond = (irms_pri**2) * Rds
        tr = mosfet.tr_ns * 1e-9; tf = mosfet.tf_ns * 1e-9
        P_sw = 0.5 * vds_required * ipk * (tr + tf) * fin.fsw * mosfet.k_sw_overlap
        Coss = (mosfet.coss_pF * 1e-12 if getattr(mosfet, 'coss_pF', None) not in (None,0) else mosfet.coss_nF * 1e-9)

        P_coss = 0.5 * Coss * (vds_required**2) * fin.fsw
        Qg = mosfet.qg_nC * 1e-9
        P_gate = Qg * mosfet.vgate_V * fin.fsw
        losses.update(dict(Pmos_cond_W=P_mos_cond, Pmos_sw_W=P_sw, Pmos_coss_W=P_coss, Pgate_W=P_gate, Pmos_total_W=(P_mos_cond+P_sw+P_coss+P_gate)))

    P_diodes = {}
    for o in outputs:
        Pcond = o.i * o.diode_drop
        Prr = 0.0
        if o.qrr_nC:
            k_i = np_turns / ns_turns[o.name]
            Vrev = fin.vin_max / k_i
            Prr = (o.qrr_nC * 1e-9) * Vrev * fin.fsw
        P_diodes[o.name] = {"Pcond_W": Pcond, "Prr_W": Prr}
    losses["Pdiodes"] = P_diodes

    P_total_loss = (Pcu_pri + sum(v["Pcu_W"] for v in Pcu_secs.values()) +
                    (p_core_W or 0.0) + P_mos_cond + P_sw + P_coss + P_gate +
                    sum(v["Pcond_W"]+v["Prr_W"] for v in P_diodes.values()))
    losses["Ptotal_W"] = P_total_loss
    eta_est = max(0.01, ini.pout_total_W / (ini.pout_total_W + P_total_loss))
    losses["eta_est"] = eta_est

    notes = dict(np_min_from_Bmax=np_turns, period_s=period)

    return RefinedDesign(
        np_turns=np_turns, ns_turns=ns_turns, k_actual_np_over_ns_main=k_act,
        gap_m=gap, lm_actual_H=lm_actual, ipk_new_A=ipk, irms_pri_new_A=irms_pri,
        dcm_ok_main=dcm_ok, t_off_main_s=toff, lsec_main_H=lsec_main,
        delta_B_T=dB, wires=wires, vds_ideal_V=vds_ideal, vds_with_overhead_V=vds_required,
        diode_vrrm_ideal_each_V=diode_vrrm_ideal_each, diode_vrrm_required_each_V=diode_vrrm_required_each,
        fill_factor=fill_factor, rcd=rcd_info, core_loss_W=p_core_W, losses=losses, notes=notes
    )

def sweep_k(fin: FlybackInput, outputs: List[OutputSpec], geom: Geometry, core: CoreParameters,
            rcd: Optional[RCDClamp]=None, stein: Optional[Steinmetz]=None, mosfet: Optional[MosfetParams]=None,
            criterion: str = "min_vds", dmin: float = 0.2, dmax: float = 0.5, dstep: float = 0.02,
            cin_vrip: float = 5.0, force_dcm: bool=False) -> Dict[str, Any]:
    main_name = fin.main_output or outputs[0].name
    grid = []
    best = None
    for D in [dmin + i*dstep for i in range(int((dmax-dmin)/dstep)+1)]:
        vref = (D/(1.0-D)) * fin.vin_min
        ini = estimate_initial_design(fin, outputs, cin_vrip=cin_vrip, vref_override=vref)
        ref = refine_with_core(fin, geom, core, ini, outputs, rcd=rcd, stein=stein, mosfet=mosfet,
                               force_dcm=force_dcm)
        vds = ref.vds_with_overhead_V
        ipk = ref.ipk_new_A
        vrrm_each = ref.diode_vrrm_required_each_V
        vrrm_max = max(vrrm_each.values())
        loss = ref.losses.get("Ptotal_W", float("inf"))
        metric = {"min_vds": vds, "min_ipk": ipk, "min_vrrm": vrrm_max, "min_loss": loss}.get(criterion, vds)
        row = {"D": D, "Vref": vref, "K": ini.k_np_over_ns, "Vds": vds, "Ipk": ipk,
               "dB_T": ref.delta_B_T, "Ploss": loss, "VRRM_max": vrrm_max,
               "ini": asdict(ini), "ref": asdict(ref)}
        for name, v in vrrm_each.items():
            row[f"VRRM_{name}"] = v
        grid.append(row)
        if best is None or metric < best["metric"]:
            best = {"metric": metric, "D": D, "ini": ini, "ref": ref}
    return {"criterion": criterion, "best": best, "grid": grid}

def normalize_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    def p(x):
        try: return parse_num(x)
        except: return x
    if "input" in cfg:
        for k in ["vin_min","vin_max","fsw","duty_max","eff","f_line","overload"]:
            if k in cfg["input"]: cfg["input"][k] = p(cfg["input"][k])
        if "force_dcm" in cfg["input"]:
            v = cfg["input"]["force_dcm"]
            if isinstance(v, str):
                cfg["input"]["force_dcm"] = v.strip().lower() in ("1","true","yes","on")
            else:
                cfg["input"]["force_dcm"] = bool(v)
    if "outputs" in cfg:
        for o in cfg["outputs"]:
            for k in ["v","i","ripple_v","diode_drop","mlt_mm","qrr_nC"]:
                if k in o: o[k] = p(o[k])
    if "core" in cfg:
        for k in ["ae_mm2","le_mm","bmax_T","al_nH_per_turn2","core_volume_mm3"]:
            if k in cfg["core"]: cfg["core"][k] = p(cfg["core"][k])
    if "geometry" in cfg:
        for k in ["jmax_A_per_mm2","mlt_pri_mm","mlt_sec_default_mm","window_area_mm2","copper_temp_C","ac_factor_pri","ac_factor_sec"]:
            if k in cfg["geometry"]: cfg["geometry"][k] = p(cfg["geometry"][k])
    if "steinmetz" in cfg:
        for k in ["k","alpha","beta"]:
            if k in cfg["steinmetz"]:
                cfg["steinmetz"][k] = p(cfg["steinmetz"][k])
        if "k_unit" in cfg["steinmetz"]:
            cfg["steinmetz"]["k_unit"] = str(cfg["steinmetz"]["k_unit"]).strip()
        if "rho_kg_per_m3" in cfg["steinmetz"]:
            cfg["steinmetz"]["rho_kg_per_m3"] = p(cfg["steinmetz"]["rho_kg_per_m3"])
    if "mosfet" in cfg:
        for k in ["rds_on_mohm","rds_temp_C","rds_temp_coeff","tr_ns","tf_ns","coss_nF","coss_pF","qg_nC","vgate_V","k_sw_overlap"]:
            if k in cfg["mosfet"]: cfg["mosfet"][k] = p(cfg["mosfet"][k])
    if "rcd" in cfg:
        for k in ["leakage_frac","vclamp_target_V","ripple_frac","margin"]:
            if k in cfg["rcd"]: cfg["rcd"][k] = p(cfg["rcd"][k])
    if "cin_vrip" in cfg: cfg["cin_vrip"] = p(cfg["cin_vrip"])
    if "k_optimize" in cfg:
        for k in ["dmin","dmax","dstep"]:
            if k in cfg["k_optimize"]:
                cfg["k_optimize"][k] = p(cfg["k_optimize"][k])
    return cfg

def load_core_library(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def run(cfg: Dict[str, Any], corelib: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = normalize_cfg(cfg)
    fin = FlybackInput(**cfg["input"])
    outs = [OutputSpec(**o) for o in cfg["outputs"]]
    cin_vrip = cfg.get("cin_vrip", 5.0)
    vref_override = cfg.get("vref_override", None)
    ini = estimate_initial_design(fin, outs, cin_vrip=cin_vrip, vref_override=vref_override)

    res = {"input": asdict(fin), "outputs":[asdict(o) for o in outs], "initial": asdict(ini)}
    if "core" in cfg and "geometry" in cfg:
        core = CoreParameters(**cfg["core"])
        geom = Geometry(**cfg["geometry"])
        stein = Steinmetz(**cfg["steinmetz"]) if "steinmetz" in cfg else None
        mosfet = MosfetParams(**cfg["mosfet"]) if "mosfet" in cfg else None
        rcd = RCDClamp(**cfg["rcd"]) if "rcd" in cfg else None

        if cfg.get("k_optimize"):
            kcfg = cfg["k_optimize"]
            crit = kcfg.get("criterion","min_vds")
            dmin = float(kcfg.get("dmin",0.2)); dmax=float(kcfg.get("dmax",0.5)); dstep=float(kcfg.get("dstep",0.02))
            sweep = sweep_k(fin, outs, geom, core, rcd=rcd, stein=stein, mosfet=mosfet, criterion=crit,
                            dmin=dmin, dmax=dmax, dstep=dstep, cin_vrip=cin_vrip,
                            force_dcm=fin.force_dcm)
            res["k_sweep"] = {"criterion": crit, "best": {"D": sweep["best"]["D"], "metric": sweep["best"]["metric"]},
                              "grid_len": len(sweep["grid"])}
            best_ini = sweep["best"]["ini"]; best_ref = sweep["best"]["ref"]
            res["initial"] = asdict(best_ini)
            res["refined"] = asdict(best_ref)
        else:
            ref = refine_with_core(fin, geom, core, ini, outs, rcd=rcd, stein=stein, mosfet=mosfet,
                                   force_dcm=fin.force_dcm)
            res["refined"] = asdict(ref)

    if corelib:
        res["core_library"] = corelib
    return res

def main():
    import argparse
    p = argparse.ArgumentParser(description="Flyback (DCM) design tool v5")
    p.add_argument("--config", type=str, help="JSON config file")
    p.add_argument("--json", action="store_true")
    p.add_argument("--corelib", type=str, help="Path to core_library_v5_with_waveforms.json", default="core_library_v5_with_waveforms.json")
    args = p.parse_args()

    if not args.config:
        print("Provide --config JSON"); sys.exit(1)
    cfg = json.load(open(args.config, "r", encoding="utf-8"))
    corelib = None
    if os.path.exists(args.corelib):
        corelib = load_core_library(args.corelib)
    res = run(cfg, corelib=corelib)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("Use --json to get structured output; or run GUI.")

if __name__ == "__main__":
    main()