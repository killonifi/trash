#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI for converter design tool with multiple topologies.
- Tabs: Inputs, Outputs, Core, Geometry, Clamp, MOSFET, K-Optimizer, Results
- Outputs managed via table + Add/Edit/Remove dialogs
- Core and MOSFET libraries can be opened from respective tabs; double-click an entry to apply
- K-Optimizer: choose criterion (min Vds / min Ipk / min max-VRRM, min total loss), scan D(Vin_min) range, apply best
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json, os, sys, re
from typing import Dict, Any
from pathlib import Path

from collections import deque
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from converter_tool.calculations.optocoupler_design import (
    InputParams,
    compute_optocoupler
)
from converter_tool.calculations.flyback_design import FlybackDesign
from converter_tool.calculations.two_switch_flyback_design import TwoSwitchFlybackDesign
from converter_tool.calculations.forward_design import ForwardDesign
from converter_tool.calculations.two_switch_forward_design import TwoSwitchForwardDesign
from converter_tool.calculations.push_pull_design import PushPullDesign
from converter_tool.calculations.half_bridge_design import HalfBridgeDesign
from converter_tool.calculations.full_bridge_design import FullBridgeDesign
from converter_tool.calculations.buck_design import BuckDesign
from converter_tool.calculations.boost_design import BoostDesign
from converter_tool.calculations.buck_boost_design import BuckBoostDesign
from converter_tool.calculations.cuk_design import CukDesign

DESIGN_MAP = {
    "Flyback": FlybackDesign,
    "2-Switch Flyback": TwoSwitchFlybackDesign,
    "Forward": ForwardDesign,
    "2-Switch Forward": TwoSwitchForwardDesign,
    "Push-Pull": PushPullDesign,
    "Half-Bridge": HalfBridgeDesign,
    "Full-Bridge": FullBridgeDesign,
    "Buck": BuckDesign,
    "Boost": BoostDesign,
    "Buck-Boost": BuckBoostDesign,
    "Ćuk": CukDesign,
    "Buck": BuckDesign,
    "Boost": BoostDesign,
    "Buck-Boost": BuckBoostDesign,
    "Ćuk": CukDesign,
}

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DEFAULT = os.path.join(PACKAGE_DIR, "core_library.json")
MOS_LIB_DEFAULT = os.path.join(PACKAGE_DIR, "mosfet_library.json")
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "Images")
IMAGE_MAP = {
    "Flyback": "flyback.png",
    "2-Switch Flyback": "Two_switch_flyback_classic_user.png",
    "Forward": "Forward.png",
    "2-Switch Forward": "Two_switch_forward.png",
    "Push-Pull": "Push-Pull.png",
    "Half-Bridge": "Half-bridge.png",
    "Full-Bridge": "Full-bridge.png",
}
# Optional improved artwork keys
IMAGE_MAP["2-Switch Flyback (Improved)"] = "Two_switch_flyback_regen.png"

OUTPUT_COLS = ("name","v","i","ripple_v","diode_drop","mlt_mm","qrr_nC")
EQUATIONS_TEXT = (
    "(1) Vref = D_min/(1−D_min)·Vin_min\n"
    "(2) K = Np/Ns = Vref/(Vout + Vf)\n"
    "(3) D(Vin) = Vref/(Vin + Vref)\n"
    "(4) Lm_target = Vin_min²·D(Vin_min)²·η/(2·Pout_max·f_sw)\n"
    "(5) Ipk = Vin_min·D(Vin_min)/(Lm·f_sw)\n"
    "(6) VDS_ideal,max = Vin_max + K·(Vout + Vf)\n"
    "(7) VRRM_sec = (Np/Ns)·Vin_max + Vout + Vf\n"
    "(8) Cout_min ≈ Iout·(1−D)/(2·ΔV·f_sw);\n"
    "    Cin_min(dc) ≈ Iin·D/ΔVin·f_sw,  Iin≈Pout/(η·Vin_min)\n"
    "(9) ΔB ≈ Vin_max·D/(Np·Ae·f_sw) → Np(min) из Bmax\n"
    "(10) g ≈ μ0·Np²·Ae / Lm_target\n"
    "(11) R_dc = ρ(T)·l/A,    P_cu = I_rms²·R_dc·k_ac\n"
    "(12) Steinmetz P_v = k·f^α·B^β,    P_core = P_v·V_core\n"
    "(13) MOSFET  P_cond,  P_sw ≈ 0.5·VDS·Ipk·(tr+tf)·f_sw·k_sw\n"
    "      P_Coss ≈ 0.5·C_OSS·VDS²·f_sw,    P_gate = Qg·Vg·f_sw\n"
    "(14) Диод  P_cond ≈ Iout·Vf;  P_rr ≈ Qrr·Vrev·f_sw\n"
)

OPTO_INFO_TEXT = r"""
Справка по оптической обратной связи (TL431+оптопара) — краткий гайд

1) Базовые определения
• Vfb — опорное напряжение компаратора ШИМ‑контроллера (вводится в Inputs).
• CTR — минимальный коэффициент передачи тока оптопары (используйте минимум по паспорту).
• f_opto = 1/(2π·Rpullup·(C2 + C_opto)) — полюс коллектора (оптопары + разделительный С2). Рекомендуйте f_opto ≥ 3…4·fc.
• «Fast‑lane» — подключение RLED к Vout. Даёт неизбежный статический коэффициент G1 = CTR·Rpullup/RLED, который нельзя сделать < требуемого |G(fc)|. Если нужно ослабление (отрицательные dB), отключайте fast‑lane.
• «No fast‑lane» — RLED сидит на фиксированном смещении (Vz). TL431 работает как ОУ; дополнительный коэффициент даёт сетевая часть (R2,C1, …).

2) Как выбрать fc (частоту пересечения)
• Начальное правило: fc ≤ min(Fsw/5, 0.3·f_opto, 0.3·f_RHPZ). Для DCM/NCP‑подобных контроллеров часто берут 0.5…2 % от Fsw.
• Учтите шум/пульсации на выходе: если пульсации заметны на FB, снижайте fc.
• По заданию по переходному процессу: чем меньше допустимый провал, тем больше fc, но с оглядкой на f_opto и RHPZ.

3) Выбор |G(fc)| в dB
• Рассчитывайте из открытого контура силовой части H(s): G(fc) = 1/|H(fc)|.
• Если требуется отрицательный dB (ослабление), fast‑lane недопустим — он имеет нижний предел G1. Используйте «no fast‑lane».

4) Тип 1 (интегратор)
• Формула ON Semiconductor: f_po = G(fc)·fc. Затем C2 = CTR/(2π·f_po·RLED) − C_opto (если получилась отрицательной — уменьшайте RLED или повышайте fc). 
• Контроль: C2 ≥ 100 пФ; f_opto ≥ 3…4·fc. Плохой признак: I_LED << 0.5 мА (рост r_d светодиода, падение запаса по фазе).

5) Тип 2 (fast‑lane)
• Симметричная расстановка: fz = fc/a, fp = fc·a, где a = √α, α = fp/fz.
• Максимальный фазовый подъем одной секции: φ_max = atan((α−1)/(2√α)) = atan((a^2−1)/(2a)).
• Практически: выберите требуемый буст φ ≤ φ_max, вычислите a, поставьте fz, fp и рассчитайте элементы. Проверьте потолок G1: если G1 > требуемого на fc — переходите на «no fast‑lane».

6) Тип 2 (no fast‑lane)
• TL431+оптопара дают G1 = CTR·Rpullup/RLED (DC), а нужное на fc ослабление/усиление формирует звено (R2,C1) / (Rpullup,C2). 
• Для симметрии берем те же fz, fp (см. п.5). Сначала проверьте ограничение оптополюсом: fp ≤ 0.3…0.5·f_opto.

7) Тип 3 (no fast‑lane)
• Две одинаковые lead‑секции: общий требуемый буст φ делим пополам: φ_each = φ/2; для каждой секции a = √α = tan(φ_each)+√(1+tan²φ_each). 
• Частоты: fz1=fz2=fc/a, fp1=fp2=fc·a. Ограничение сверху: fp ≤ 0.3…0.5·f_opto.
• Учитывайте, что С_opto добавляется к C2 коллектора — реальная верхняя пара полюсов ниже расчётной при большом C_opto.

8) Ограничения на RLED (DC)
• Fast‑lane: RLED ≤ [(Vout−Vf−Vref)/(Vdd−VCEsat+Ibias·CTR·Rpullup)]·Rpullup·CTR.
• No fast‑lane: RLED ≤ [(Vz−Vf−Vref)/(Vdd−VCEsat+Ibias·CTR·Rpullup)]·Rpullup·CTR.
• Вводите 10…20 % запаса вниз. Поддерживайте Ibias(TL431) ≥ 1 мА (иначе открытый усиление TL431 падает на ~10 dB).

9) Полезные проверки
• Мargin по оптополюсу: f_opto/fc ≥ 3 — хороший, <2 — пересмотрите Rpullup, C_opto, fc.
• Оценка r_d светодиода: r_d ≈ 25 мВ/I_LED; при I_LED < 0.5 мА r_d сотни Ом (учтено в расчёте G1) и заметно снижает фактический G1.
• Все номиналы оконтролить в AC‑модели (Bode): проверьте φm ≥ 45…60°, GM ≥ 6…10 dB.

Термин «a»
• Это геометрический коэффициент разнесения полюса и нуля относительно fc: fz = fc/a, fp = fc·a. Он равен √α, где α = fp/fz. 
• Через «a» выражается предельный фазовый буст: φ_max = atan((a²−1)/(2a)).
"""

def add_copy_menu(widget: tk.Widget):
    menu = tk.Menu(widget, tearoff=0)
    menu.add_command(label="Copy", command=lambda: widget.event_generate('<<Copy>>'))
    widget.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
class Tooltip(tk.Toplevel):
    def __init__(self, widget, text="", **kw):
        super().__init__(widget, **kw)
        self.wm_overrideredirect(True)
        self.label = tk.Label(self, text=text, justify="left", background="#ffffe0", relief="solid", borderwidth=1, font=("Tahoma", 9))
        self.label.pack(ipadx=4, ipady=2)
class OutputDialog(tk.Toplevel):
    def __init__(self, master, data=None):
        super().__init__(master)
        self.title("Output editor")
        self.resizable(False, False)
        self.result=None
        self.vars = {k: tk.StringVar() for k in ["name","v","i","ripple_v","diode_drop","mlt_mm","qrr_nC"]}
        if data:
            for k in self.vars:
                if k in data and data[k] is not None:
                    self.vars[k].set(str(data[k]))
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        row=0
        for lbl, key in [("Name","name"),("Vout [V]","v"),("Iout [A]","i"),
                         ("Ripple Vpp [V]","ripple_v"),("Diode Vf [V]","diode_drop"),
                         ("MLT sec [mm]","mlt_mm"),("Qrr [nC] (opt)","qrr_nC")]:
            ttk.Label(frm, text=lbl).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(frm, textvariable=self.vars[key], width=22).grid(row=row, column=1, sticky="w", pady=2)
            row+=1
        btns = ttk.Frame(frm); btns.grid(row=row, column=0, columnspan=2, pady=8, sticky="ew")
        ttk.Button(btns, text="OK", command=self.ok).pack(side="left", padx=5)
        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="left", padx=5)
    def ok(self):
        d = {k: self.vars[k].get().strip() or None for k in self.vars}
        if not d["name"] or not d["v"] or not d["i"]:
            messagebox.showerror("Error", "name, Vout, Iout are required"); return
        self.result = d; self.destroy()
    def cancel(self): self.result=None; self.destroy()

class CoreEditDialog(tk.Toplevel):
    def __init__(self, master, data=None):
        super().__init__(master)
        self.title("Core editor")
        self.result=None
        fields=["distributor","distributor_sku","vendor","series","size","material","Ae_mm2","le_mm","Ve_mm3","Aw_mm2","Bmax_T","AL_nH_per_turn2_ungapped","k","alpha","beta"]
        self.vars={k: tk.StringVar() for k in fields}
        self.k_unit_var = tk.StringVar(value="W/kg")
        if data:
            for k in fields:
                v = data.get(k)
                if v is not None:
                    self.vars[k].set(str(v))
            st = data.get("steinmetz")
            if isinstance(st, dict):
                for k in ["k","alpha","beta"]:
                    if st.get(k) is not None:
                        self.vars[k].set(str(st[k]))
                if st.get("k_unit"):
                    self.k_unit_var.set(st["k_unit"])
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        labels=[
            ("Distributor","distributor"),("SKU","distributor_sku"),("Vendor","vendor"),("Series","series"),("Size","size"),("Material","material"),
            ("Ae [mm²]","Ae_mm2"),("le [mm]","le_mm"),("Ve [mm³]","Ve_mm3"),("Aw [mm²]","Aw_mm2"),("Bmax [T]","Bmax_T"),("AL [nH/turn²]","AL_nH_per_turn2_ungapped"),
            ("k","k"),("alpha","alpha"),("beta","beta")
        ]
        row=0
        for lbl,key in labels:
            ttk.Label(frm, text=lbl).grid(row=row, column=0, sticky="w", pady=2)
            if key=="k":
                ttk.Entry(frm, textvariable=self.vars[key], width=20).grid(row=row, column=1, sticky="w", pady=2)
                ttk.Combobox(frm, textvariable=self.k_unit_var, values=["W/m3","W/kg"], width=6, state="readonly").grid(row=row, column=2, sticky="w", padx=4)
            else:
                ttk.Entry(frm, textvariable=self.vars[key], width=22).grid(row=row, column=1, columnspan=2, sticky="w", pady=2)
            row+=1
        btns = ttk.Frame(frm); btns.grid(row=row, column=0, columnspan=3, pady=8)
        ttk.Button(btns, text="OK", command=self.ok).pack(side="left", padx=5)
        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="left", padx=5)
    def ok(self):
        d = {k: self.vars[k].get().strip() or None for k in self.vars}
        st = {"k": d.pop("k", None), "alpha": d.pop("alpha", None), "beta": d.pop("beta", None), "k_unit": self.k_unit_var.get()}
        d["steinmetz"] = st
        # convert numeric fields
        for k in ["Ae_mm2","le_mm","Ve_mm3","Aw_mm2","Bmax_T","AL_nH_per_turn2_ungapped"]:
            if d.get(k) not in (None, ""):
                try: d[k] = float(d[k])
                except: pass
        for k in ["k","alpha","beta"]:
            if st.get(k) not in (None, ""):
                try: st[k] = float(st[k])
                except: pass
        self.result=d
        self.destroy()
    def cancel(self):
        self.result=None
        self.destroy()

class MosfetEditDialog(tk.Toplevel):
    def __init__(self, master, data=None):
        super().__init__(master)
        self.title("MOSFET editor")
        self.result=None
        fields=["name","vds_V","rds_on_mohm","qg_nC","coss_pF","tr_ns","tf_ns","vgate_V","rds_temp_C","rds_temp_coeff","k_sw_overlap"]
        self.vars={k: tk.StringVar() for k in fields}
        if data:
            for k in fields:
                v=data.get(k)
                if v is not None:
                    self.vars[k].set(str(v))
        frm = ttk.Frame(self, padding=10); frm.pack(fill="both", expand=True)
        row=0
        for lbl,key in [
            ("Name","name"),("Vds max [V]","vds_V"),("Rds_on [mΩ]","rds_on_mohm"),("Qg [nC]","qg_nC"),("Coss [pF]","coss_pF"),("tr [ns]","tr_ns"),("tf [ns]","tf_ns"),("Vgate [V]","vgate_V"),("Rds temp [°C]","rds_temp_C"),("Rds temp coeff","rds_temp_coeff"),("k_sw_overlap","k_sw_overlap")]:
            ttk.Label(frm, text=lbl).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(frm, textvariable=self.vars[key], width=22).grid(row=row, column=1, sticky="w", pady=2)
            row+=1
        btns = ttk.Frame(frm); btns.grid(row=row, column=0, columnspan=2, pady=8)
        ttk.Button(btns, text="OK", command=self.ok).pack(side="left", padx=5)
        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="left", padx=5)
    def ok(self):
        d = {k: self.vars[k].get().strip() or None for k in self.vars}
        for k in d:
            if k!="name" and d[k] not in (None, ""):
                try: d[k] = float(d[k])
                except: pass
        self.result=d
        self.destroy()
    def cancel(self):
        self.result=None
        self.destroy()

class CoreLibraryWindow(tk.Toplevel):
    def __init__(self, master, apply_cb):
        super().__init__(master)
        self.title("Core library")
        self.apply_cb = apply_cb
        self.path = LIB_DEFAULT
        self.filter_var = tk.StringVar()
        top = ttk.Frame(self, padding=6); top.pack(fill="x")
        ttk.Button(top, text="Load...", command=self.load_file).pack(side="left")
        ttk.Button(top, text="Save", command=self.save_file).pack(side="left", padx=4)
        ttk.Button(top, text="Use selected", command=self.use_selected).pack(side="left", padx=4)
        ttk.Label(top, text="Filter").pack(side="right")
        ttk.Entry(top, textvariable=self.filter_var, width=20).pack(side="right", padx=4)
        self.filter_var.trace_add('write', lambda *a: self.apply_filter())
        cols=("distributor","distributor_sku","vendor","series","size","material","Ae_mm2","le_mm","Ve_mm3","Aw_mm2","Bmax_T","AL_nH_per_turn2_ungapped")
        self.cols = cols
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c)
            w = 120 if c in ("distributor_sku","size") else 90
            if c in ("Ae_mm2","le_mm","Ve_mm3","Aw_mm2","Bmax_T","AL_nH_per_turn2_ungapped"): w=110
            self.tree.column(c, width=w, anchor="center", stretch=False)
        ysb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.pack(fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        self.tree.bind("<Double-1>", lambda e: self.use_selected())
        btns = ttk.Frame(self, padding=6); btns.pack(fill="x")
        ttk.Button(btns, text="Add", command=self.add_item).pack(side="left")
        ttk.Button(btns, text="Edit", command=self.edit_item).pack(side="left", padx=4)
        ttk.Button(btns, text="Remove", command=self.remove_item).pack(side="left", padx=4)
        self.all_items=[]
        self.items_by_iid={}
        if os.path.exists(self.path):
            self.load_file(initial=True)

    def load_file(self, initial=False):
        if not initial:
            path = filedialog.askopenfilename(filetypes=[("JSON","*.json"),("All","*.*")])
            if not path: return
            self.path = path
        data = json.load(open(self.path,"r",encoding="utf-8")) if os.path.exists(self.path) else {"cores":[]}
        self.all_items = data.get("cores", [])
        self.apply_filter()

    def save_file(self):
        json.dump({"cores": self.all_items}, open(self.path,"w",encoding="utf-8"), indent=2)
        messagebox.showinfo("Saved", self.path)

    def apply_filter(self):
        txt = self.filter_var.get().lower()
        for iid in list(self.tree.get_children()):
            self.tree.delete(iid)
        self.items_by_iid={}
        for it in self.all_items:
            joined = " ".join(str(it.get(k,"")) for k in it.keys()).lower()
            if txt in joined:
                vals = ["" if it.get(k) is None else str(it.get(k)) for k in self.cols]
                iid = self.tree.insert("", "end", values=vals)
                self.items_by_iid[iid]=it

    def use_selected(self):
        sel = self.tree.selection()
        if not sel: return
        item = self.items_by_iid[sel[0]]
        self.apply_cb(item)
        self.destroy()

    def add_item(self):
        d = CoreEditDialog(self)
        self.wait_window(d)
        if d.result:
            self.all_items.append(d.result)
            self.apply_filter()

    def edit_item(self):
        sel = self.tree.selection()
        if not sel: return
        item = self.items_by_iid[sel[0]]
        d = CoreEditDialog(self, data=item)
        self.wait_window(d)
        if d.result:
            idx = self.all_items.index(item)
            self.all_items[idx] = d.result
            self.apply_filter()

    def remove_item(self):
        sel = self.tree.selection()
        if not sel: return
        item = self.items_by_iid[sel[0]]
        self.all_items.remove(item)
        self.apply_filter()


class OptoLibraryWindow(tk.Toplevel):
    def __init__(self, master, lib_path):
        super().__init__(master)
        self.title("Optocoupler Library")
        self.geometry("640x320")
        self.master = master
        self.lib_path = lib_path
        cols = ("model","vendor","ctr_min","copto_nf","vce_sat","notes")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        for c,w in zip(cols,(120,120,80,80,80,200)):
            self.tree.heading(c, text=c); self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        btns = ttk.Frame(self); btns.pack(fill="x")
        ttk.Button(btns, text="Apply", command=self.apply).pack(side="left", padx=6, pady=6)
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right", padx=6, pady=6)
        try:
            data = json.load(open(self.lib_path, "r", encoding="utf-8"))
        except Exception:
            data = []
        for it in data:
            self.tree.insert("", "end", values=(it.get("model",""), it.get("vendor",""), it.get("ctr_min",""),
                                                it.get("copto_nf",""), it.get("vce_sat",""), it.get("notes","")))
    def apply(self):
        sel = self.tree.selection()
        if not sel: return
        model, vendor, ctr_min, copto_nf, vce_sat, notes = self.tree.item(sel[0], "values")
        try:
            self.master.opto_vars["ctr_min"].set(str(ctr_min))
            self.master.opto_vars["c_opto_nf"].set(str(copto_nf))
            self.master.opto_vars["vce_sat"].set(str(vce_sat))
            # Store model name in hidden var if present
            if "opto_model" in self.master.opto_vars:
                self.master.opto_vars["opto_model"].set(str(model))
        except Exception:
            pass
        self.destroy()
class MosfetLibraryWindow(tk.Toplevel):
    def __init__(self, master, apply_cb):
        super().__init__(master)
        self.title("MOSFET library")
        self.apply_cb = apply_cb
        self.path = MOS_LIB_DEFAULT
        self.filter_var = tk.StringVar()
        top = ttk.Frame(self, padding=6); top.pack(fill="x")
        ttk.Button(top, text="Load...", command=self.load_file).pack(side="left")
        ttk.Button(top, text="Save", command=self.save_file).pack(side="left", padx=4)
        ttk.Button(top, text="Use selected", command=self.use_selected).pack(side="left", padx=4)
        ttk.Label(top, text="Filter").pack(side="right")
        ttk.Entry(top, textvariable=self.filter_var, width=20).pack(side="right", padx=4)
        self.filter_var.trace_add('write', lambda *a: self.apply_filter())
        cols=("name","vds_V","rds_on_mohm","qg_nC","coss_pF","tr_ns","tf_ns","vgate_V","rds_temp_C","rds_temp_coeff","k_sw_overlap")
        self.cols=cols
        self.tree=ttk.Treeview(self, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=100, anchor="center", stretch=False)
        ysb=ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xsb=ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.pack(fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        self.tree.bind("<Double-1>", lambda e: self.use_selected())
        btns = ttk.Frame(self, padding=6); btns.pack(fill="x")
        ttk.Button(btns, text="Add", command=self.add_item).pack(side="left")
        ttk.Button(btns, text="Edit", command=self.edit_item).pack(side="left", padx=4)
        ttk.Button(btns, text="Remove", command=self.remove_item).pack(side="left", padx=4)
        self.all_items=[]
        self.items_by_iid={}
        if os.path.exists(self.path):
            self.load_file(initial=True)

    def load_file(self, initial=False):
        if not initial:
            path = filedialog.askopenfilename(filetypes=[("JSON","*.json"),("All","*.*")])
            if not path: return
            self.path = path
        data = json.load(open(self.path,"r",encoding="utf-8")) if os.path.exists(self.path) else {"mosfets":[]}
        self.all_items = data.get("mosfets", [])
        self.apply_filter()

    def save_file(self):
        json.dump({"mosfets": self.all_items}, open(self.path,"w",encoding="utf-8"), indent=2)
        messagebox.showinfo("Saved", self.path)

    def apply_filter(self):
        txt = self.filter_var.get().lower()
        for iid in list(self.tree.get_children()):
            self.tree.delete(iid)
        self.items_by_iid={}
        for it in self.all_items:
            joined = " ".join(str(it.get(k,"")) for k in it.keys()).lower()
            if txt in joined:
                vals=["" if it.get(k) is None else str(it.get(k)) for k in self.cols]
                iid=self.tree.insert("", "end", values=vals)
                self.items_by_iid[iid]=it

    def use_selected(self):
        sel=self.tree.selection()
        if not sel: return
        item=self.items_by_iid[sel[0]]
        self.apply_cb(item)
        self.destroy()

    def add_item(self):
        d=MosfetEditDialog(self)
        self.wait_window(d)
        if d.result:
            self.all_items.append(d.result)
            self.apply_filter()

    def edit_item(self):
        sel=self.tree.selection()
        if not sel: return
        item=self.items_by_iid[sel[0]]
        d=MosfetEditDialog(self, data=item)
        self.wait_window(d)
        if d.result:
            idx=self.all_items.index(item)
            self.all_items[idx]=d.result
            self.apply_filter()

    def remove_item(self):
        sel=self.tree.selection()
        if not sel: return
        item=self.items_by_iid[sel[0]]
        self.all_items.remove(item)
        self.apply_filter()

class ChatWindow(tk.Toplevel):
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.title("ChatGPT")
        self.master = master
        self.client = None
        key_frame = ttk.Frame(self, padding=6)
        key_frame.pack(fill="x")
        ttk.Label(key_frame, text="API key:").pack(side="left")
        self.api_key_var = tk.StringVar()
        ttk.Entry(key_frame, textvariable=self.api_key_var, show="*", width=40).pack(side="left", padx=4)
        ttk.Button(key_frame, text="Connect", command=self.set_api_key).pack(side="left")
        self.chat_display = tk.Text(self, wrap="word")
        self.chat_display.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.chat_display.bind("<Key>", lambda e: "break")
        add_copy_menu(self.chat_display)
        bottom = ttk.Frame(self)
        bottom.pack(fill="x")
        self.chat_entry = ttk.Entry(bottom)
        self.chat_entry.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        self.send_btn = ttk.Button(bottom, text="Send", command=self.send_chat, state="disabled")
        self.send_btn.pack(side="left", padx=4)

    def set_api_key(self):
        key = self.api_key_var.get().strip()
        if not key:
            messagebox.showerror("API key", "Введите API ключ")
            return
        self.client = OpenAI(api_key=key)
        self.send_btn.config(state="normal")
        self.chat_entry.config(state="normal")

    def send_chat(self):
        msg = self.chat_entry.get().strip()
        if not msg:
            return
        self.chat_entry.delete(0, "end")
        self.chat_display.insert("end", f"Вы: {msg}\n")
        context = self.master.collect_cfg()
        try:
            resp = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Ты помощник по проектированию преобразователей. Если хочешь изменить поля, верни JSON с парами поле:значение."},
                    {"role": "user", "content": msg + "\n" + json.dumps(context, ensure_ascii=False)}
                ],
            )
            reply = resp.choices[0].message.content
        except Exception as e:
            reply = f"Ошибка: {e}"
        self.chat_display.insert("end", f"ChatGPT: {reply}\n")
        self.chat_display.see("end")
        self.master.handle_chat_changes(reply)
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Converter Design Tool")
        self.geometry("1100x760")
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=6, relief="flat")
        style.configure("Accent.TButton", padding=6, foreground="white", background="#0078D7", relief="flat")
        style.map("Accent.TButton", background=[("active", "#005A9E")])
        style.configure("Chat.TButton", padding=6, foreground="white", background="#1E90FF", relief="flat")
        style.map("Chat.TButton", background=[("active", "#1C86EE")])
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("Info.TLabel", foreground="#0078D7")
        self.option_add("*Font", "{Segoe UI} 10")

        topbar = ttk.Frame(self); topbar.pack(fill="x")
        ttk.Label(topbar, text="Topology:").pack(side="left", padx=4)
        self.topology_var = tk.StringVar(value="Flyback")
        topo_cb = ttk.Combobox(topbar, textvariable=self.topology_var,
                               values=list(DESIGN_MAP.keys()), state="readonly", width=14)
        topo_cb.pack(side="left")
        topo_cb.bind("<<ComboboxSelected>>", self.change_topology)
        center = ttk.Frame(topbar)
        center.pack(side="left", expand=True, fill="x")
        ttk.Button(center, text="ChatGPT", command=self.open_chat, style="Chat.TButton").pack()
        ttk.Button(topbar, text="Compute", command=self.compute, style="Accent.TButton").pack(side="right", padx=4)
        self.design_cls = DESIGN_MAP[self.topology_var.get()]
        self.design = self.design_cls()

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self.nb = nb
        self.model: Dict[str, Any] = {
            "input": {"vin_min":"90","vin_max":"265","fsw":"100k","duty_max":"0.45","eff":"0.88","input_type":"dc","f_line":"50","overload":"1.2","cin_vrip":"5","min_load_pct":"10","force_dcm": False, "soft_switch": False},
            "outputs": [{"name":"12V","v":"12","i":"5","ripple_v":"0.06","diode_drop":"0.5","mlt_mm":"40"}],
            "core": {"ae_mm2":"58","le_mm":"57","bmax_T":"0.20","core_volume_mm3":"3310"},
            "geometry": {"jmax_A_per_mm2":"4.0","mlt_pri_mm":"40","mlt_sec_default_mm":"40","window_area_mm2":"70","copper_temp_C":"60","ac_factor_pri":"1.5","ac_factor_sec":"1.5"},
            "rcd": {"enable": True, "leakage_frac":"0.015","vclamp_target_V":"450","ripple_frac":"0.1","return_to_bus": True},
            "mosfet": {"vds_V":"600","rds_on_mohm":"150","rds_temp_C":"100","rds_temp_coeff":"0.004","tr_ns":"30","tf_ns":"30","coss_pF":"100","qg_nC":"40","vgate_V":"10","k_sw_overlap":"1.0"},
            "steinmetz": {"k":"3.2","k_unit":"W/kg","alpha":"1.5","beta":"2.6"},
            "k_optimize": {"criterion":"min_vds","dmin":"0.22","dmax":"0.48","dstep":"0.02"}
        }
        self.build_inputs_tab()
        self.build_outputs_tab()
        self.build_core_tab()
        self.build_geom_tab()
        self.build_clamp_tab()
        self.build_mosfet_tab()
        self.build_k_tab()
        self.build_results_tab()
        self.build_optocoupler_tab()
        self.create_menu()
        self.setup_undo()
    def create_menu(self):
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Load JSON...", command=self.load_json)
        fm.add_command(label="Save JSON...", command=self.save_json)
        fm.add_separator()
        fm.add_command(label="Compute", command=self.compute)
        fm.add_separator()
        fm.add_command(label="Exit", command=self.destroy)
        m.add_cascade(label="File", menu=fm)
        info = tk.Menu(m, tearoff=0)
        info.add_command(label="Equations", command=self.show_equations)
        info.add_command(label="AWG", command=self.show_awg_table)
        info.add_command(label="Optocoupler", command=self.show_opto_info)
        m.add_cascade(label="Info", menu=info)
        self.config(menu=m)

    def open_chat(self):
        if getattr(self, "chat_win", None) and self.chat_win.winfo_exists():
            self.chat_win.lift()
            return
        self.chat_win = ChatWindow(self)
        
    def change_topology(self, *args):
        name = self.topology_var.get()
        self.design_cls = DESIGN_MAP[name]
        self.design = self.design_cls()
        self.title(f"Converter Design Tool - {name}")
        self.update_soft2t_visibility()
        self.update_topology_image()

    def show_equations(self):
        win = tk.Toplevel(self)
        win.title("Equations")
        txt = tk.Text(win, wrap="word", width=80, height=24)
        ysb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=ysb.set)
        txt.insert("1.0", EQUATIONS_TEXT)
        txt.configure(state="disabled")
        txt.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
    def show_awg_table(self):
        win = tk.Toplevel(self)
        win.title("AWG Table")
        cols = ("AWG", "Area mm²")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for c in cols:
            tree.heading(c, text=c)
            w = 80 if c == "AWG" else 100
            tree.column(c, width=w, anchor="center")
        ysb = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ysb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        table = getattr(self.design, "AWG_TABLE", [])
        if not table:
            ttk.Label(win, text="AWG table not available for this topology").grid(row=0, column=0)
            return
        for g, a in table:
            tree.insert("", "end", values=(f"AWG{self.design.awg_str(g)}", f"{a:.4f}"))

    def show_opto_info(self):
        win = tk.Toplevel(self)
        win.title("Optocoupler Info")
        txt = tk.Text(win, wrap="word", width=80, height=24)
        ysb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=ysb.set)
        txt.insert("1.0", OPTO_INFO_TEXT)
        txt.configure(state="disabled")
        txt.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

    def add_tooltip(self, widget, text: str):
        tip = Tooltip(widget, text=text)
        tip.withdraw()

        def enter(e):
            tip.deiconify()
            tip.wm_geometry(f"+{e.x_root + 10}+{e.y_root + 10}")

        def leave(e):
            tip.withdraw()

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)
    def build_inputs_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Inputs")
        input_keys = [k for k in self.model["input"].keys() if k not in ("force_dcm","soft_switch")]
        self.inputs_vars = {k: tk.StringVar(value=str(self.model["input"].get(k,""))) for k in input_keys}
        self.force_dcm_var = tk.BooleanVar(value=bool(self.model["input"].get("force_dcm", False)))
        self.soft2t_var = tk.BooleanVar(value=bool(self.model["input"].get("soft_switch", False)))
        container = ttk.Frame(tab)
        container.pack(fill="both", expand=True)
        grid = ttk.Frame(container, padding=10); grid.pack(side="left", fill="both", expand=True)
        img_frame = ttk.Frame(container, padding=10); img_frame.pack(side="right", fill="y")
        self.topology_image_label = ttk.Label(img_frame)
        self.topology_image_label.pack()
        labels = [
            ("Vin min [V]", "vin_min", "Minimum input voltage"),
            ("Vin max [V]", "vin_max", "Maximum input voltage"),
            ("f_sw [Hz]", "fsw", "Switching frequency"),
            ("Duty max", "duty_max", "Maximum duty cycle at Vin_min"),
            ("Efficiency", "eff", "Expected efficiency"),
            ("Input type", "input_type", None),
            ("Line freq [Hz]", "f_line", "AC line frequency"),
            ("Overload factor", "overload", "Allowable overload"),
            ("Cin ripple [Vpp]", "cin_vrip", "Allowed input capacitor ripple"),
            ("Min Load [%]", "min_load_pct", "Minimum load for calculations"),
        ]
        row = 0
        for lbl, key, tip in labels:
            if key == "f_line":
                self.f_line_label = ttk.Frame(grid)
                self.f_line_label.grid(row=row, column=0, sticky="w", pady=3)
                ttk.Label(self.f_line_label, text=lbl).pack(side="left")
                if tip:
                    info = ttk.Label(self.f_line_label, text="?", style="Info.TLabel")
                    info.pack(side="left", padx=2)
                    self.add_tooltip(info, tip)
                self.f_line_entry = ttk.Entry(grid, textvariable=self.inputs_vars[key], width=20)
                self.f_line_entry.grid(row=row, column=1, sticky="w", pady=3)
            else:
                lf = ttk.Frame(grid)
                lf.grid(row=row, column=0, sticky="w", pady=3)
                ttk.Label(lf, text=lbl).pack(side="left")
                if tip:
                    info = ttk.Label(lf, text="?", style="Info.TLabel")
                    info.pack(side="left", padx=2)
                    self.add_tooltip(info, tip)
                if key == "input_type":
                    self.input_type_cb = ttk.Combobox(
                        grid, textvariable=self.inputs_vars[key], values=("dc", "ac"), state="readonly", width=18
                    )
                    self.input_type_cb.grid(row=row, column=1, sticky="w", pady=3)
                    self.input_type_cb.bind("<<ComboboxSelected>>", self.update_f_line_visibility)
                else:
                    ttk.Entry(grid, textvariable=self.inputs_vars[key], width=20).grid(row=row, column=1, sticky="w", pady=3)
            row += 1
        ttk.Checkbutton(grid, text="Force DCM", variable=self.force_dcm_var).grid(row=row, column=0, sticky="w", pady=3)
        row += 1
        self.soft2t_row = row
        self.soft2t_cb = ttk.Checkbutton(grid, text="Improved 2T (regenerative soft-switch)", variable=self.soft2t_var, command=self.update_topology_image)
        self.update_f_line_visibility()
        self.update_soft2t_visibility()
        self.update_topology_image()


    def update_f_line_visibility(self, *args):
        if self.inputs_vars["input_type"].get().lower() == "dc":
            self.f_line_label.grid_remove()
            self.f_line_entry.grid_remove()
        else:
            self.f_line_label.grid()
            self.f_line_entry.grid()

    def update_soft2t_visibility(self):
        if not hasattr(self, "soft2t_cb"):
            return
        if self.topology_var.get() == "2-Switch Flyback":
            self.soft2t_cb.grid(row=self.soft2t_row, column=0, columnspan=2, sticky="w", pady=3)
            self.soft2t_cb.state(["!disabled"])
        else:
            self.soft2t_var.set(False)
            self.soft2t_cb.grid_remove()

    def update_topology_image(self):
        name = self.topology_var.get()
        fname = IMAGE_MAP.get(name)
        if name == "2-Switch Flyback" and bool(self.soft2t_var.get()):
            # Use improved topology artwork when checkbox enabled
            fname = IMAGE_MAP.get("2-Switch Flyback (Improved)") or fname
        if not fname:
            return
        path = os.path.join(IMAGES_DIR, fname)
        if os.path.exists(path):
            try:
                self.topology_image = tk.PhotoImage(file=path)
                self.topology_image_label.configure(image=self.topology_image)
                if hasattr(self, "res_topology_image_label"):
                    self.res_topology_image_label.configure(image=self.topology_image)
            except Exception:
                pass
    def build_outputs_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Outputs")
        frm = ttk.Frame(tab, padding=10); frm.pack(fill="both", expand=True)
        table = ttk.Frame(frm)
        table.pack(fill="both", expand=True, side="left")
        cols = OUTPUT_COLS
        self.tree = ttk.Treeview(table, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=110, anchor="center", stretch=False)
        ysb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        for o in self.model["outputs"]:
            self.tree.insert("", "end", values=[o.get(c,"") for c in cols])
        btns = ttk.Frame(frm); btns.pack(side="left", fill="y", padx=6)
        ttk.Button(btns, text="Add", command=self.add_output).pack(fill="x", padx=5, pady=5)
        ttk.Button(btns, text="Edit", command=self.edit_output).pack(fill="x", padx=5, pady=5)
        ttk.Button(btns, text="Remove", command=self.remove_output).pack(fill="x", padx=5, pady=5)
    def build_core_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Core")
        core = self.model["core"]
        self.core_vars = {k: tk.StringVar(value=str(core.get(k,""))) for k in ["ae_mm2","le_mm","bmax_T","core_volume_mm3","al_nH_per_turn2"]}
        s = self.model.get("steinmetz", {})
        self.st_vars = {k: tk.StringVar(value=str(s.get(k,""))) for k in ["k","alpha","beta"]}
        self.st_unit_var = tk.StringVar(value=s.get("k_unit","W/kg"))
        grid = ttk.Frame(tab, padding=10); grid.pack(fill="both", expand=True)
        ttk.Button(grid, text="Choose from library", command=self.open_core_library).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0,6))
        labels=[("Ae [mm²]","ae_mm2"),("le [mm]","le_mm"),("Bmax [T]","bmax_T"),("Core volume [mm³]","core_volume_mm3"),("AL [nH/turn²] (opt)","al_nH_per_turn2")]
        start=1
        for r,(lbl,k) in enumerate(labels, start=start):
            ttk.Label(grid, text=lbl).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=self.core_vars[k], width=20).grid(row=r, column=1, sticky="w", pady=3)
        row = start + len(labels)
        ttk.Label(grid, text="Steinmetz k").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(grid, textvariable=self.st_vars["k"], width=20).grid(row=row, column=1, sticky="w", pady=3)
        ttk.Combobox(grid, textvariable=self.st_unit_var, values=["W/m3","W/kg"], width=6, state="readonly").grid(row=row, column=2, sticky="w", padx=4)
        row+=1
        ttk.Label(grid, text="alpha").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(grid, textvariable=self.st_vars["alpha"], width=20).grid(row=row, column=1, sticky="w", pady=3)
        row+=1
        ttk.Label(grid, text="beta").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(grid, textvariable=self.st_vars["beta"], width=20).grid(row=row, column=1, sticky="w", pady=3)
    def build_geom_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Geometry/Wire")
        g = self.model["geometry"]
        self.geom_vars = {k: tk.StringVar(value=str(g.get(k,""))) for k in ["jmax_A_per_mm2","mlt_pri_mm","mlt_sec_default_mm","window_area_mm2","copper_temp_C","ac_factor_pri","ac_factor_sec"]}
        grid = ttk.Frame(tab, padding=10); grid.pack(fill="both", expand=True)
        labels=[("Jmax [A/mm²]","jmax_A_per_mm2"),("MLT primary [mm]","mlt_pri_mm"),("MLT sec default [mm]","mlt_sec_default_mm"),
                ("Window [mm²]","window_area_mm2"),("Copper temp [°C]","copper_temp_C"),("AC factor pri","ac_factor_pri"),("AC factor sec","ac_factor_sec")]
        for r,(lbl,k) in enumerate(labels):
            ttk.Label(grid, text=lbl).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=self.geom_vars[k], width=20).grid(row=r, column=1, sticky="w", pady=3)
    def build_clamp_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Clamp (RCD)")
        r = self.model["rcd"]
        self.rcd_vars = {
            "enable": tk.BooleanVar(value=bool(r.get("enable", True))),
            "leakage_frac": tk.StringVar(value=str(r.get("leakage_frac","0.015"))),
            "vclamp_target_V": tk.StringVar(value=str(r.get("vclamp_target_V","450"))),
            "ripple_frac": tk.StringVar(value=str(r.get("ripple_frac","0.1"))),
            "return_to_bus": tk.BooleanVar(value=bool(r.get("return_to_bus", True))),
        }
        grid = ttk.Frame(tab, padding=10); grid.pack(fill="both", expand=True)
        ttk.Checkbutton(grid, text="Enable RCD clamp", variable=self.rcd_vars["enable"]).grid(row=0, column=0, sticky="w")
        row=1
        for lbl,k in [("Leakage frac","leakage_frac"),("Vclamp [V]","vclamp_target_V"),("Clamp ripple frac","ripple_frac")]:
            ttk.Label(grid, text=lbl).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=self.rcd_vars[k], width=20).grid(row=row, column=1, sticky="w", pady=3)
            row+=1
        ttk.Checkbutton(grid, text="Return R to bus", variable=self.rcd_vars["return_to_bus"]).grid(row=row, column=0, sticky="w")
    def build_mosfet_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="MOSFET")
        m = self.model["mosfet"]
        self.mos_vars = {k: tk.StringVar(value=str(m.get(k,""))) for k in ["vds_V","rds_on_mohm","rds_temp_C","rds_temp_coeff","tr_ns","tf_ns","coss_pF","qg_nC","vgate_V","k_sw_overlap"]}
        grid = ttk.Frame(tab, padding=10); grid.pack(fill="both", expand=True)
        ttk.Button(grid, text="Choose from library", command=self.open_mosfet_library).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,6))
        labels=[("Vds max [V]","vds_V"),("Rds_on [mΩ]","rds_on_mohm"),("Tj for Rds [°C]","rds_temp_C"),("Rds temp coeff [1/K]","rds_temp_coeff"),
                ("tr [ns]","tr_ns"),("tf [ns]","tf_ns"),("Coss [pF]","coss_pF"),("Qg [nC]","qg_nC"),("Vgate [V]","vgate_V"),("k_sw_overlap","k_sw_overlap")]
        start=1
        for r,(lbl,k) in enumerate(labels, start=start):
            ttk.Label(grid, text=lbl).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=self.mos_vars[k], width=20).grid(row=r, column=1, sticky="w", pady=3)
    def open_core_library(self):
        CoreLibraryWindow(self, self.apply_core_from_library)
    def open_mosfet_library(self):
        MosfetLibraryWindow(self, self.apply_mosfet_from_library)
    def apply_core_from_library(self, item):
        mapping = {"ae_mm2": item.get("Ae_mm2"), "le_mm": item.get("le_mm"), "bmax_T": item.get("Bmax_T"), "al_nH_per_turn2": item.get("AL_nH_per_turn2_ungapped")}
        for k,v in mapping.items():
            if v is not None and k in self.core_vars:
                self.core_vars[k].set(str(v))
        ve = item.get("Ve_mm3")
        if ve is not None:
            self.core_vars["core_volume_mm3"].set(str(ve))
        st = item.get("steinmetz")
        if isinstance(st, dict):
            for k in ["k","alpha","beta"]:
                v = st.get(k)
                if v is not None:
                    self.st_vars[k].set(str(v))
            unit = st.get("k_unit")
            if unit:
                self.st_unit_var.set(unit)
    def apply_mosfet_from_library(self, item):
        for k in self.mos_vars:
            v = item.get(k)
            if v is not None:
                self.mos_vars[k].set(str(v))
    def build_k_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="K-Optimizer")
        self.k_vars = {"criterion": tk.StringVar(value=self.model["k_optimize"].get("criterion","min_vds")),
                       "dmin": tk.StringVar(value=self.model["k_optimize"].get("dmin","0.22")),
                       "dmax": tk.StringVar(value=self.model["k_optimize"].get("dmax","0.48")),
                       "dstep": tk.StringVar(value=self.model["k_optimize"].get("dstep","0.02"))}
        grid = ttk.Frame(tab, padding=10); grid.pack(fill="x")
        ttk.Label(grid, text="Criterion:").grid(row=0, column=0, sticky="w")
        crit = ttk.Combobox(grid, textvariable=self.k_vars["criterion"], values=["min_vds","min_ipk","min_vrrm","min_loss"], width=12, state="readonly")
        crit.grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(grid, text="D(Vin_min) range:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(grid, textvariable=self.k_vars["dmin"], width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(grid, text="..").grid(row=1, column=2, sticky="w")
        ttk.Entry(grid, textvariable=self.k_vars["dmax"], width=8).grid(row=1, column=3, sticky="w")
        ttk.Label(grid, text="step").grid(row=1, column=4, sticky="w")
        ttk.Entry(grid, textvariable=self.k_vars["dstep"], width=8).grid(row=1, column=5, sticky="w")
        btns = ttk.Frame(tab, padding=8); btns.pack(fill="x")
        ttk.Button(btns, text="Run sweep", command=self.run_sweep, style="Accent.TButton").pack(side="left", padx=5)
        ttk.Button(btns, text="Apply best K", command=self.apply_best, style="Accent.TButton").pack(side="left", padx=5)
        result_frame = ttk.Frame(tab, padding=8)
        result_frame.pack(fill="both", expand=True)
        self.k_result = tk.Text(result_frame, height=16, wrap="none", font=("Consolas", 10))
        ysb = ttk.Scrollbar(result_frame, orient="vertical", command=self.k_result.yview)
        xsb = ttk.Scrollbar(result_frame, orient="horizontal", command=self.k_result.xview)
        self.k_result.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.k_result.grid(row=0, column=0, sticky="nsew")
        add_copy_menu(self.k_result)
        self.k_result.bind("<Double-Button-1>", self.on_k_result_double_click)
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
    def build_results_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Results")
        top = ttk.Frame(tab, padding=6); top.pack(fill="x")
        ttk.Button(top, text="Compute", command=self.compute, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(top, text="Save report...", command=self.save_report, style="Accent.TButton").pack(side="left", padx=4)
        content = ttk.Frame(tab)
        content.pack(fill="both", expand=True)
        text_frame = ttk.Frame(content)
        text_frame.pack(side="left", fill="both", expand=True)
        self.res_text = tk.Text(text_frame, wrap="none", font=("Consolas", 10))
        ysb = ttk.Scrollbar(text_frame, orient="vertical", command=self.res_text.yview)
        xsb = ttk.Scrollbar(text_frame, orient="horizontal", command=self.res_text.xview)
        self.res_text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.res_text.grid(row=0, column=0, sticky="nsew")
        add_copy_menu(self.res_text)
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        img_frame = ttk.Frame(content, padding=10); img_frame.pack(side="right", fill="y")
        self.res_topology_image_label = ttk.Label(img_frame)
        self.res_topology_image_label.pack()
        if hasattr(self, "topology_image"):
            self.res_topology_image_label.configure(image=self.topology_image)
        # Preload defaults from current model
        try:
            self.load_opto_defaults()
        except Exception:
            pass

    def load_opto_defaults(self):
        # Take defaults from the normalized configuration (Inputs/Outputs)
        cfg = self.collect_cfg()
        cfg_norm = self.design.normalize_cfg(cfg)
        vout = cfg_norm["outputs"][0]["v"]
        fsw = cfg_norm["input"]["fsw"]
        self.opto_vars["v_out"].set(str(vout))
        self.opto_vars["f_sw"].set(str(fsw))
    
    def build_optocoupler_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Optocoupler")
        body = ttk.Frame(tab); body.pack(fill="both", expand=True)
        # Left pane with inputs
        left = ttk.Frame(body, padding=6); left.pack(side="left", fill="y")
        self.opto_vars = {k: tk.StringVar() for k in [
            "v_out","f_sw","vdd","r_pullup","ctr_min","c_opto_nf","v_ref",
            "v_f_led","vce_sat","i_div_uA","v_bias_zener","i_bias_mA","vfb",
            "fc","gc_db","boost_deg","opto_model","comp_type",
        ]}
        # defaults
        self.opto_vars["v_out"].set("12.0")
        self.opto_vars["f_sw"].set("100000")
        self.opto_vars["vdd"].set("5.0")
        self.opto_vars["r_pullup"].set("20000")
        self.opto_vars["ctr_min"].set("0.3")
        self.opto_vars["c_opto_nf"].set("2.0")
        self.opto_vars["v_ref"].set("2.5")
        self.opto_vars["v_f_led"].set("1.0")
        self.opto_vars["vce_sat"].set("0.3")
        self.opto_vars["vfb"].set("2.5")
        self.opto_vars["i_div_uA"].set("250")
        self.opto_vars["v_bias_zener"].set("6.2")
        self.opto_vars["i_bias_mA"].set("1.0")
        self.opto_vars["fc"].set("1000")
        self.opto_vars["gc_db"].set("-10")
        self.opto_vars["boost_deg"].set("60")
        self.opto_vars["comp_type"].set("type3")

        self.opto_field_frames = {}

        def add_row(parent, r, label, key, hint=None):
            frm = ttk.Frame(parent); frm.grid(row=r, column=0, columnspan=2, sticky="w", pady=1)
            ttk.Label(frm, text=label).pack(side="left")
            e = ttk.Entry(frm, textvariable=self.opto_vars[key], width=12); e.pack(side="left", padx=(6,0))
            if hint:
                q = ttk.Label(frm, text="?", style="Info.TLabel")
                q.pack(side="left", padx=4)
                self.add_tooltip(q, hint)
            self.opto_field_frames[key] = frm
            return e
        r=0

        # --- Compensation type selector ---
        ttk.Label(left, text="Compensator type").grid(row=r, column=0, sticky="w")
        type_cb = ttk.Combobox(left, state="readonly",
                               values=["type1","type2","type2_fast","type3"],
                               textvariable=self.opto_vars["comp_type"], width=16)
        type_cb.grid(row=r, column=1, sticky="ew", pady=2)
        type_cb.bind("<<ComboboxSelected>>", self.on_comp_type_changed)
        r += 1
        r += 1
        add_row(left, r, "Vout, V", "v_out", "Основной выход, В"); r+=1
        add_row(left, r, "Fsw (from Inputs), Hz", "f_sw", "Частота контроллера, подтягивается с вкладки Inputs"); r+=1
        ttk.Separator(left, orient="horizontal").grid(row=r, column=0, columnspan=2, sticky="ew", pady=4); r+=1
        add_row(left, r, "Vdd, V", "vdd", "Питание коллектора оптопары"); r+=1
        add_row(left, r, "Rpullup, Ω", "r_pullup", "↑R→больше усиление (через CTR·Rpullup/RLED), но ниже f_opto"); r+=1
        add_row(left, r, "CTR(min)", "ctr_min", "Минимальный CTR в рабочей точке"); r+=1
        add_row(left, r, "Copto, nF", "c_opto_nf", "Паразитическая ёмкость коллектора оптопары"); r+=1
        ttk.Separator(left, orient="horizontal").grid(row=r, column=0, columnspan=2, sticky="ew", pady=4); r+=1
        add_row(left, r, "Vref TL431, V", "v_ref", "Опорное TL431 (≈2.5 В)"); r+=1
        add_row(left, r, "Vf LED, V", "v_f_led", "Падение на LED при рабочем токе"); r+=1
        add_row(left, r, "VCE(sat), V", "vce_sat", "Насыщение фототранзистора"); r+=1
        add_row(left, r, "Idiv, µA", "i_div_uA", "Ток делителя TL431; ≥150 µA"); r+=1
        add_row(left, r, "Vbias (zener), V", "v_bias_zener", "Стабилитрон узла смещения LED"); r+=1
        add_row(left, r, "Ibias TL431, mA", "i_bias_mA", "Доп. ток смещения TL431 через Rbias"); r+=1
        add_row(left, r, "Vfb ref, V", "vfb", "Порог компаратора FB контроллера"); r+=1
        ttk.Separator(left, orient="horizontal").grid(row=r, column=0, columnspan=2, sticky="ew", pady=4); r+=1
        add_row(left, r, "fc, Hz", "fc", "Желаемая частота пересечения петли"); r+=1
        add_row(left, r, "G(fc), dB", "gc_db", "Модуль компенсатор+опто в fc"); r+=1
        add_row(left, r, "Boost, deg", "boost_deg", "Требуемое фазовое приращение"); r+=1

        btns = ttk.Frame(left); btns.grid(row=r, column=0, columnspan=2, pady=6, sticky="w")
        ttk.Button(btns, text="Load defaults from model", command=self.load_opto_defaults).pack(side="left", padx=2)
        ttk.Button(btns, text="Open Optocoupler Library", command=lambda: OptoLibraryWindow(self, os.path.join(PACKAGE_DIR, "optocoupler_library.json"))).pack(side="left", padx=6)
        ttk.Button(btns, text="Compute", command=self.compute_optocoupler, style="Accent.TButton").pack(side="left", padx=6)

        
        # Right: image + tabs
        right = ttk.Frame(body); right.pack(side="left", fill="both", expand=True)
        imgf = ttk.Frame(right, padding=(6,6,6,0)); imgf.pack(fill="x")
        self.opto_img_label = ttk.Label(imgf)
        self.opto_img_label.pack(anchor="w")
        try:
            candidates = ["Optocoupler.png","optocoupler.png","Optocoupler.PNG","optocoupler.PNG"]
            img_path = None
            for name in candidates:
                pth = os.path.join(IMAGES_DIR, name)
                if os.path.exists(pth):
                    img_path = pth; break
            if img_path:
                self.opto_img = tk.PhotoImage(file=img_path)
                self.opto_img_label.configure(image=self.opto_img)
            else:
                self.opto_img_label.configure(text="(optocoupler image not available)")
        except Exception:
            self.opto_img_label.configure(text="(optocoupler image not available)")

        inner = ttk.Notebook(right); inner.pack(fill="both", expand=True, padx=6, pady=6)
        res_tab = ttk.Frame(inner); inner.add(res_tab, text="Results")
        info_tab = ttk.Frame(inner); inner.add(info_tab, text="Info")

        # Results text widget
        res_frame = ttk.Frame(res_tab)
        res_frame.pack(fill="both", expand=True)
        self.opto_text = tk.Text(res_frame, wrap="none", font=("Consolas", 10))
        ysb = ttk.Scrollbar(res_frame, orient="vertical", command=self.opto_text.yview)
        xsb = ttk.Scrollbar(res_frame, orient="horizontal", command=self.opto_text.xview)
        self.opto_text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.opto_text.grid(row=0, column=0, sticky="nsew")
        add_copy_menu(self.opto_text)
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        res_frame.columnconfigure(0, weight=1)
        res_frame.rowconfigure(0, weight=1)

        # Info text
        info = tk.Text(info_tab, wrap="word", font=("Segoe UI", 10))
        info.pack(fill="both", expand=True)
        info.insert("1.0", OPTO_INFO_TEXT)
        info.config(state="disabled")

        # Preload defaults
        try:
            self.load_opto_defaults()
        except Exception:
            pass
        self.on_comp_type_changed()

    def load_opto_defaults(self):
        # Take defaults from the normalized configuration (Inputs/Outputs)
        cfg = self.collect_cfg()
        cfg_norm = self.design.normalize_cfg(cfg)
        vout = cfg_norm["outputs"][0]["v"]
        fsw = cfg_norm["input"]["fsw"]
        self.opto_vars["v_out"].set(str(vout))
        self.opto_vars["f_sw"].set(str(fsw))

    def add_output(self):
        d = OutputDialog(self); self.wait_window(d)
        if d.result:
            idx = len(self.model["outputs"])
            self.model["outputs"].append(d.result)
            iid = self.tree.insert("", "end", values=[d.result.get(c,"") for c in OUTPUT_COLS])
            def undo():
                del self.model["outputs"][idx]
                self.tree.delete(iid)
            def redo():
                self.model["outputs"].insert(idx, d.result)
                self.tree.insert("", idx, iid=iid, values=[d.result.get(c,"") for c in OUTPUT_COLS])
            self.undo_stack.append((undo, redo))
            self.redo_stack.clear()
    def edit_output(self):
        sel = self.tree.selection()
        if not sel: return
        iid = sel[0]
        idx = self.tree.index(iid)
        data = self.model["outputs"][idx]
        old = data.copy()
        d = OutputDialog(self, data=data); self.wait_window(d)
        if d.result:
            self.model["outputs"][idx] = d.result
            self.tree.item(iid, values=[d.result.get(c,"") for c in OUTPUT_COLS])
            def undo():
                self.model["outputs"][idx] = old
                self.tree.item(iid, values=[old.get(c,"") for c in OUTPUT_COLS])
            def redo():
                self.model["outputs"][idx] = d.result
                self.tree.item(iid, values=[d.result.get(c,"") for c in OUTPUT_COLS])
            self.undo_stack.append((undo, redo))
            self.redo_stack.clear()
    def remove_output(self):
        sel = self.tree.selection()
        if not sel: return
        iid = sel[0]
        idx = self.tree.index(iid)
        data = self.model["outputs"].pop(idx)
        self.tree.delete(iid)
        def undo():
            self.model["outputs"].insert(idx, data)
            self.tree.insert("", idx, iid=iid, values=[data.get(c,"") for c in OUTPUT_COLS])
        def redo():
            del self.model["outputs"][idx]
            self.tree.delete(iid)
        self.undo_stack.append((undo, redo))
        self.redo_stack.clear()
    def collect_cfg(self) -> Dict[str, Any]:
        inp = {k: v.get() for k,v in self.inputs_vars.items()}
        inp["force_dcm"] = bool(self.force_dcm_var.get())
        if self.topology_var.get() == "2-Switch Flyback":
            inp["soft_switch"] = bool(self.soft2t_var.get())
        outs=[]
        for iid in self.tree.get_children():
            vals = self.tree.item(iid,"values")
            keys=("name","v","i","ripple_v","diode_drop","mlt_mm","qrr_nC")
            outs.append({k: vals[i] for i,k in enumerate(keys)})
        core = {k: v.get() for k,v in self.core_vars.items()}
        geom = {k: v.get() for k,v in self.geom_vars.items()}
        rcd = {"enable": bool(self.rcd_vars["enable"].get()),
               "leakage_frac": self.rcd_vars["leakage_frac"].get(),
               "vclamp_target_V": self.rcd_vars["vclamp_target_V"].get(),
               "ripple_frac": self.rcd_vars["ripple_frac"].get(),
               "return_to_bus": bool(self.rcd_vars["return_to_bus"].get())}
        mos = {k: v.get() for k,v in self.mos_vars.items()}
        st = {k: v.get() for k,v in self.st_vars.items()}
        st["k_unit"] = self.st_unit_var.get()
        kopt = {k: v.get() for k,v in self.k_vars.items()}
        cfg = {"input": inp, "outputs": outs, "core": core, "geometry": geom, "rcd": rcd, "mosfet": mos, "steinmetz": st, "k_optimize": kopt}
        return cfg
    def compute(self):
        try:
            cfg = self.collect_cfg()
            cfg_norm = self.design.normalize_cfg(cfg)
            res = self.design.run_calculation(cfg_norm)
            self.show_results(res)
            self.compute_optocoupler(cfg_norm)
        except NotImplementedError:
            messagebox.showinfo("Not implemented", "Selected topology is not yet implemented")
        except Exception as e:
            messagebox.showerror("Compute error", str(e))
    def compute_optocoupler(self, cfg_norm=None):
        try:
            if cfg_norm is None:
                cfg = self.collect_cfg()
                cfg_norm = self.design.normalize_cfg(cfg)
            g = {k: self.opto_vars[k].get().strip() for k in self.opto_vars}
            def fget(k, default):
                try:
                    return float(g.get(k) or default)
                except Exception:
                    return float(default)
            params = InputParams(
                v_out = fget("v_out", cfg_norm["outputs"][0]["v"]),
                f_sw  = fget("f_sw", cfg_norm["input"]["fsw"]),
                vdd   = fget("vdd", 5.0),
                r_pullup = fget("r_pullup", 20_000.0),
                ctr_min  = fget("ctr_min", 0.3),
                c_opto_nf = fget("c_opto_nf", 2.0),
                v_ref    = fget("v_ref", 2.5),
                v_f_led  = fget("v_f_led", 1.0),
                vce_sat  = fget("vce_sat", 0.3),
                i_div_uA = fget("i_div_uA", 250.0),
                v_bias_zener = fget("v_bias_zener", 6.2),
                i_bias_mA    = fget("i_bias_mA", 1.0),
                vfb    = fget("vfb", 2.5),
                fc      = fget("fc", 1000.0),
                gc_db   = fget("gc_db", -10.0),
                boost_deg = fget("boost_deg", 60.0),
                comp_type = g.get("comp_type", "type3"),
            )
            report = compute_optocoupler(params)
            self.opto_text.delete("1.0", "end")
            self.opto_text.insert("1.0", report.get("report_text", ""))
        except Exception as e:
            self.opto_text.delete("1.0", "end")
            self.opto_text.insert("1.0", f"Error: {e}")
    def on_comp_type_changed(self, event=None):
        t = self.opto_vars["comp_type"].get().strip().lower()
        visible = {"v_out","f_sw","vdd","r_pullup","ctr_min","c_opto_nf",
                   "v_ref","v_f_led","vce_sat","i_div_uA","i_bias_mA",
                   "vfb","fc","gc_db"}
        if t != "type1":
            visible.add("boost_deg")
        if t in {"type2", "type3"}:
            visible.add("v_bias_zener")
        for key, frm in self.opto_field_frames.items():
            frm.grid() if key in visible else frm.grid_remove()
        img_name = {"type1":"Optocoupler_type1.png","type2":"Optocoupler_type2.png",
                    "type2_fast":"Optocoupler_type2_fast_lane.png","type3":"Optocoupler_type3.png"}.get(t, "Optocoupler_type1.png")
        pth = os.path.join(IMAGES_DIR, img_name)
        if os.path.exists(pth):
            self.opto_img = tk.PhotoImage(file=pth); self.opto_img_label.configure(image=self.opto_img, text="")
        else:
            self.opto_img_label.configure(image="", text="(optocoupler image not available)")
        try:
            self.compute_optocoupler()
        except Exception:
            pass

    def run_sweep(self):
        if not hasattr(self.design, "sweep_k"):
            messagebox.showinfo("K-optimizer", "Sweep not supported for this topology")
            return
        try:
            cfg = self.collect_cfg()
            cfg_norm = self.design.normalize_cfg(cfg)
            fin = self.design.InputClass(**cfg_norm["input"])
            outs = [self.design.OutputSpec(**o) for o in cfg_norm["outputs"]]
            core = self.design.CoreParameters(**cfg_norm["core"])
            geom = self.design.Geometry(**cfg_norm["geometry"])
            stein = self.design.Steinmetz(**cfg_norm["steinmetz"]) if "steinmetz" in cfg_norm else None
            mos = self.design.MosfetParams(**cfg_norm["mosfet"]) if "mosfet" in cfg_norm else None
            rcd = self.design.RCDClamp(**cfg_norm["rcd"]) if "rcd" in cfg_norm else None
            crit = self.k_vars["criterion"].get()
            dmin=float(self.k_vars["dmin"].get()); dmax=float(self.k_vars["dmax"].get()); dstep=float(self.k_vars["dstep"].get())
            sweep = self.design.sweep_k(fin, outs, geom, core, rcd=rcd, stein=stein, mosfet=mos, criterion=crit,
                             dmin=dmin, dmax=dmax, dstep=dstep,
                             force_dcm=fin.force_dcm)
            lines = [f"Criterion: {crit}"]
            col_specs = [
                ("D", lambda r: r["D"], "{:>6.3f}", 6),
                ("Vref[V]", lambda r: r["Vref"], "{:>8.1f}", 8),
                ("K_ideal", lambda r: r["K"], "{:>8.3f}", 8),
                ("Vds[V]", lambda r: r["Vds"], "{:>8.1f}", 8),
                ("Ipk[A]", lambda r: r["Ipk"], "{:>8.2f}", 8),
                ("ΔB[T]", lambda r: r["dB_T"], "{:>8.3f}", 8),
            ]
            for o in outs:
                col_specs.append((f"VRRM_{o.name}[V]", lambda r, nm=o.name: r[f"VRRM_{nm}"], "{:>10.1f}", 10))
            col_specs.append(("Ploss[W]", lambda r: r["Ploss"], "{:>10.2f}", 10))
            header_line = " ".join(f"{name:>{width}}" for name, _, _, width in col_specs)
            lines.append(header_line)
            for row in sweep["grid"]:
                line = " ".join(fmt.format(fn(row)) for _, fn, fmt, _ in col_specs)
                lines.append(line)
            best = sweep["best"]
            lines.append("")
            lines.append(f"BEST: D={best['D']:.3f}, ΔB={best['ref'].delta_B_T:.3f} T")
            self.k_result.delete("1.0","end"); self.k_result.insert("1.0", "\n".join(lines))
            self.sweep_cache = sweep
        except NotImplementedError:
            messagebox.showinfo("K-optimizer", "Selected topology is not yet implemented")
        except Exception as e:
            messagebox.showerror("K-optimizer", str(e))

    def on_k_result_double_click(self, event):
        if not hasattr(self, "sweep_cache"):
            return
        idx = self.k_result.index(f"@{event.x},{event.y}")
        line = int(idx.split(".")[0])
        row_idx = line - 3  # skip criterion and header
        rows = self.sweep_cache.get("grid", [])
        if 0 <= row_idx < len(rows):
            Dval = rows[row_idx]["D"]
            self.inputs_vars["duty_max"].set(f"{Dval:.4f}")
            messagebox.showinfo("K-optimizer", f"Применено: D(Vin_min)={Dval:.3f}. Пересчитайте (Compute).")

    def apply_best(self):
        if not hasattr(self, "sweep_cache"):
            messagebox.showinfo("K-optimizer", "Run sweep first."); return
        Dbest = self.sweep_cache["best"]["D"]
        self.inputs_vars["duty_max"].set(f"{Dbest:.4f}")
        messagebox.showinfo("K-optimizer", f"Применено: D(Vin_min)={Dbest:.3f}. Пересчитайте (Compute).")
    def handle_chat_changes(self, text: str):
        m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
        if not m:
            return
        try:
            changes = json.loads(m.group(1))
        except Exception:
            return
        for field, val in changes.items():
            var = self.find_var(field)
            if var and messagebox.askyesno("Подтвердите", f"Изменить {field} на {val}?"):
                var.set(str(val))
    def find_var(self, field: str):
        for d in [self.inputs_vars, self.core_vars, self.geom_vars, self.mos_vars, self.st_vars, self.rcd_vars]:
            if field in d:
                return d[field]
        return None
    def setup_undo(self):
        self.undo_stack = deque(maxlen=15)
        self.redo_stack = deque(maxlen=15)
        for d in [self.inputs_vars, self.core_vars, self.geom_vars, self.mos_vars, self.st_vars]:
            for v in d.values():
                self._track_var(v)
        for v in self.rcd_vars.values():
            self._track_var(v)
    def _track_var(self, var):
        var._last = var.get()
        def cb(*_):
            new = var.get()
            old = var._last
            if new == old:
                return
            def undo():
                var.set(old)
            def redo():
                var.set(new)
            self.undo_stack.append((undo, redo))
            self.redo_stack.clear()
            var._last = new
        var.trace_add('write', cb)
    def undo(self):
        if not getattr(self, 'undo_stack', None):
            return
        if not self.undo_stack:
            return
        undo, redo = self.undo_stack.pop()
        undo()
        self.redo_stack.append((redo, undo))
    def redo(self):
        if not getattr(self, 'redo_stack', None):
            return
        if not self.redo_stack:
            return
        redo, undo = self.redo_stack.pop()
        redo()
        self.undo_stack.append((undo, redo))
    def show_results(self, res: Dict[str, Any]):
        self.res_text.delete("1.0","end")
        if "initial" not in res:
            self.res_text.insert("1.0", json.dumps(res, indent=2, ensure_ascii=False))
            return
        lines = []
        ini = res["initial"]
        lines.append("=== ЭТАП 1 (без сердечника) ===")
        lines.append(f"Pout_total = {ini['pout_total_W']:.3f} W")
        lines.append(f"Lm_target = {ini['lm_target_H']:.6e} H")
        lines.append(f"Ipk = {ini['ipk_A']:.3f} A")
        lines.append(f"Irms_primary = {ini['irms_pri_A']:.3f} A")
        lines.append(f"D_used = {ini['d_used']:.3f}")
        lines.append(f"D(Vin_min) = {ini['d_vin_min']:.3f}")
        lines.append(f"D(Vin_max) = {ini['d_vin_max']:.3f}")
        lines.append(f"K(Np/Ns) main = {ini['k_np_over_ns']:.3f}")
        lines.append(f"Vref (Reflected Voltage) = {ini['vref_V']:.2f} V")
        lines.append(f"VDS_ideal_max = {ini['vds_ideal_max_V']:.2f} V")
        for name, c in ini["cout_min_each_F"].items():
            lines.append(f"Cout_min[{name}] = {c:.6e} F")
        lines.append(f"Cin_min = {ini['cin_min_F']:.6e} F")
        if "refined" in res:
            r = res["refined"]
            lines.append("")
            lines.append("=== ЭТАП 2 (с сердечником) ===")
            lines.append(f"Np = {r['np_turns']}")
            lines.append(f"Ns per output = {r['ns_turns']}")
            lines.append(f"K_actual(main) = {r['k_actual_np_over_ns_main']:.3f}")
            lines.append(f"Gap = {r['gap_m']*1e3:.3f} мм")
            lines.append(f"Lm_actual = {r['lm_actual_H']:.6e} H")
            lines.append(f"Ipk(actual) = {r['ipk_new_A']:.3f} A")
            lines.append(f"Irms_primary(actual) = {r['irms_pri_new_A']:.3f} A")
            lines.append(f"t_off(main) = {r['t_off_main_s']*1e6:.3f} мкс")
            lines.append(f"DCM_ok = {r['dcm_ok_main']}")
            lines.append(f"VDS ideal = {r['vds_ideal_V']:.2f} V")
            lines.append(f"VDS with clamp = {r['vds_with_overhead_V']:.2f} V")
            lines.append(f"ΔB = {r['delta_B_T']:.3f} T")
            if r.get('ss0_core_cm4') is not None:
                lines.append(f"SS0_core = {r['ss0_core_cm4']:.3f} см^4")
            if r.get('ss0_min_cm4') is not None:
                lines.append(f"SS0_min = {r['ss0_min_cm4']:.3f} см^4")
            vref = ini['vref_V']
            for o in res["outputs"]:
                name = o["name"]
                ns = r["ns_turns"][name]
                k_i = r["np_turns"] / ns
                vout_real = vref / k_i - o.get("diode_drop", 0.0)
                lines.append(f"Vout_real[{name}] = {vout_real:.2f} V")
            lines.append("")
            if r.get('diode_vrrm_required_each_V'):
                for name, v in r['diode_vrrm_required_each_V'].items():
                    lines.append(f"VRRM[{name}] = {v:.2f} V")
            if res.get('ratings'):
                lines.append("--- RATING CHECKS ---")
                for k, v in res['ratings'].items():
                    lines.append(f"{k} = {v:.2f}x")
            if res.get('warnings'):
                lines.append("WARNINGS:")
                for w in res['warnings']:
                    lines.append(f"! {w}")
            if r.get('rcd'):
                rc = r['rcd']
                lines.append(f"RCD clamp: Vclamp = {rc['Vclamp_V']:.1f} V; C = {rc['C_snub_F']:.3e} F; R = {rc['R_snub_Ohm']:.1f} Ω; P_snub = {rc['P_lk_W']:.2f} W")
            lines.append("--- ПРОВОДНИКИ ---")
            lines.append(f"Skin depth ≈ {r['wires']['skin_depth_mm']:.3f} мм")
            lines.append(
                f"A_cu_primary = {r['wires']['primary_area_mm2']:.6f} мм^2 -> {r['wires']['primary_awg']}"
                f" ({r['wires']['primary_awg_area_mm2']:.3f} мм^2) x{int(r['wires']['primary_parallel'])}"
            )
            for o in res["outputs"]:
                name = o["name"]
                lines.append(
                    f"A_cu_sec[{name}] = {r['wires'][name+'_area_mm2']:.6f} мм^2 -> {r['wires'][name+'_awg']}"
                    f" ({r['wires'][name+'_awg_area_mm2']:.3f} мм^2) x{int(r['wires'][name+'_parallel'])}"
                )
            if r["fill_factor"] is not None:
                lines.append(f"Fill-factor ≈ {r['fill_factor']:.2f}")
            lines.append("")
            lines.append("--- ПОТЕРИ ---")
            loss = r["losses"]
            lines.append(f"Pcu_primary = {loss['Pcu_pri_W']:.2f} W (Rdc_pri = {loss['Rdc_pri_Ohm']:.4f} Ω)")
            for name, v in loss["Pcu_secs"].items():
                lines.append(f"Pcu_sec[{name}] = {v['Pcu_W']:.2f} W (Rdc = {v['Rdc_Ohm']:.4f} Ω)")
            if "Pcore_W" in loss:
                lines.append(f"Pcore = {loss['Pcore_W']:.2f} W")
            for k in ["Pmos_cond_W","Pmos_sw_W","Pmos_coss_W","Pgate_W"]:
                if k in loss: lines.append(f"{k} = {loss[k]:.2f} W")
            lines.append("Диоды:")
            for name,v in loss["Pdiodes"].items():
                lines.append(f"  {name}: Pcond = {v['Pcond_W']:.2f} W; Prr = {v['Prr_W']:.2f} W")
            lines.append(f"Σ P_losses = {loss['Ptotal_W']:.2f} W")
            lines.append(f"η_est ≈ {loss['eta_est']*100:.1f} %")
        else:
            lines.append("")
            lines.append("(Этап 2 не выполнен — задайте Core и Geometry)")
        self.res_text.insert("1.0", "\n".join(lines))
        self.res_text.tag_config("warning", foreground="red")
        self.res_text.tag_config("key", foreground="#0078D7")
        for idx, line in enumerate(lines, start=1):
            if line.startswith("!"):
                self.res_text.tag_add("warning", f"{idx}.0", f"{idx}.end")
            if line.startswith("η_est"):
                self.res_text.tag_add("key", f"{idx}.0", f"{idx}.end")
    def save_json(self):
        cfg = self.collect_cfg()
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json"),("All","*.*")])
        if not path: return
        json.dump(cfg, open(path,"w",encoding="utf-8"), indent=2)
        messagebox.showinfo("Saved", path)
    def load_json(self):
        path = filedialog.askopenfilename(filetypes=[("JSON","*.json"),("All","*.*")])
        if not path: return
        try:

            cfg = json.load(open(path,"r",encoding="utf-8"))
            # migrate cin_vrip from root to input if needed
            if "cin_vrip" in cfg and "input" in cfg:
                cfg["input"]["cin_vrip"] = cfg.pop("cin_vrip")
            if "cin_vrrip" in cfg and "input" in cfg:
                cfg["input"]["cin_vrip"] = cfg.pop("cin_vrrip")
            core = cfg.get("core", {})
            if "bmax_T" not in core:
                for alt in ("bmax", "Bmax", "Bmax_T"):
                    if alt in core:
                        core["bmax_T"] = core[alt]
                        break
            cfg["core"] = core
            self.model = cfg
            for w in self.nb.winfo_children():
                w.destroy()
            self.build_inputs_tab()
            self.build_outputs_tab()
            self.build_core_tab()
            self.build_geom_tab()
            self.build_clamp_tab()
            self.build_mosfet_tab()
            self.build_k_tab()
            self.build_results_tab()
            self.build_optocoupler_tab()
            self.setup_undo()
        except Exception as e:
            messagebox.showerror("Load JSON error", str(e))
    def save_report(self):
        data = self.res_text.get("1.0","end").strip()
        if not data:
            messagebox.showinfo("Nothing to save", "Сначала выполните Compute."); return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text","*.txt"),("All","*.*")])
        if not path: return
        open(path,"w",encoding="utf-8").write(data)
        messagebox.showinfo("Saved", path)
if __name__ == "__main__":
    app = App(); app.mainloop()
