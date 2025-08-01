#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI for Flyback Design Tool v5 (DCM)
- Tabs: Inputs, Outputs, Core, Geometry, Clamp, MOSFET, Steinmetz, K-Optimizer, Core Library, Results
- Outputs managed via table + Add/Edit/Remove dialogs
- Core Library tab shows a table of distributor parts; hover shows tooltip with parameters; double-click to apply
- K-Optimizer: choose criterion (min Vds / min Ipk / min VRRM / min total loss), scan D(Vin_min) range, apply best
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json, os
from typing import Dict, Any
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.figure as mplfig
try:
    from flyback_design_v5 import (
        parse_num, FlybackInput, OutputSpec, Geometry, CoreParameters, Steinmetz,
        RCDClamp, MosfetParams, estimate_initial_design, refine_with_core, run, normalize_cfg, sweep_k
    )
    HAVE_CORE = True
except Exception as e:
    HAVE_CORE = False
    IMPORT_ERR = str(e)
LIB_DEFAULT = "core_library_v5.json"
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
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Flyback Design Tool v5 (DCM)")
        self.geometry("1100x760")
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self.nb = nb
        self.model: Dict[str, Any] = {
            "input": {"vin_min":"90","vin_max":"265","fsw":"100k","duty_max":"0.45","eff":"0.88","input_type":"dc","f_line":"50","overload":"1.2","main_output":"","cin_vrip":"5"},
            "outputs": [{"name":"12V","v":"12","i":"5","ripple_v":"0.06","diode_drop":"0.5","mlt_mm":"40"}],
            "core": {"ae_mm2":"58","le_mm":"57","bmax_T":"0.20","core_volume_mm3":"3310"},
            "geometry": {"jmax_A_per_mm2":"4.0","mlt_pri_mm":"40","mlt_sec_default_mm":"40","window_area_mm2":"70","copper_temp_C":"60","ac_factor_pri":"1.5","ac_factor_sec":"1.5"},
            "rcd": {"enable": True, "leakage_frac":"0.015","vclamp_target_V":"450","ripple_frac":"0.1","return_to_bus": True},
            "mosfet": {"rds_on_mohm":"150","rds_temp_C":"100","rds_temp_coeff":"0.004","tr_ns":"30","tf_ns":"30","coss_nF":"100","qg_nC":"40","vgate_V":"10","k_sw_overlap":"1.0"},
            "steinmetz": {"k":"3.2","alpha":"1.5","beta":"2.6"},
            "k_optimize": {"criterion":"min_vds","dmin":"0.22","dmax":"0.48","dstep":"0.02"}
        }
        self.build_inputs_tab()
        self.build_outputs_tab()
        self.build_core_tab()
        self.build_geom_tab()
        self.build_clamp_tab()
        self.build_mosfet_tab()
        self.build_stein_tab()
        self.build_k_tab()
        self.build_library_tab()
        self.build_waveforms_tab()
        self.build_transformer_tab()
        self.build_results_tab()
        self.create_menu()
    def create_menu(self):
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Load JSON...", command=self.load_json)
        fm.add_command(label="Save JSON...", command=self.save_json)
        fm.add_separator()
        fm.add_command(label="Load Core Library...", command=self.load_library)
        fm.add_separator()
        fm.add_command(label="Compute", command=self.compute)
        fm.add_separator()
        fm.add_command(label="Exit", command=self.destroy)
        m.add_cascade(label="File", menu=fm)
        self.config(menu=m)
    def build_inputs_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Inputs")
        self.inputs_vars = {k: tk.StringVar(value=str(self.model["input"].get(k,""))) for k in self.model["input"].keys()}
        grid = ttk.Frame(tab, padding=10); grid.pack(fill="both", expand=True)
        labels=[("Vin_min [V]","vin_min"),("Vin_max [V]","vin_max"),("fsw [Hz]","fsw"),("Dmax","duty_max"),
                ("eff","eff"),("input_type (dc/ac)","input_type"),("f_line [Hz]","f_line"),
                ("overload","overload"),("main_output name","main_output"),("Cin ripple [Vpp]","cin_vrip")]
        row=0
        for lbl,key in labels:
            ttk.Label(grid, text=lbl).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=self.inputs_vars[key], width=20).grid(row=row, column=1, sticky="w", pady=3)
            row+=1
    def build_outputs_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Outputs")
        frm = ttk.Frame(tab, padding=10); frm.pack(fill="both", expand=True)
        cols=("name","v","i","ripple_v","diode_drop","mlt_mm","qrr_nC")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c); self.tree.column(c, width=110, anchor="center")
        self.tree.pack(fill="both", expand=True, side="left")
        for o in self.model["outputs"]:
            self.tree.insert("", "end", values=[o.get(c,"") for c in cols])
        btns = ttk.Frame(frm); btns.pack(side="right", fill="y")
        ttk.Button(btns, text="Add", command=self.add_output).pack(fill="x", padx=5, pady=5)
        ttk.Button(btns, text="Edit", command=self.edit_output).pack(fill="x", padx=5, pady=5)
        ttk.Button(btns, text="Remove", command=self.remove_output).pack(fill="x", padx=5, pady=5)
    def build_core_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Core")
        core = self.model["core"]
        self.core_vars = {k: tk.StringVar(value=str(core.get(k,""))) for k in ["ae_mm2","le_mm","bmax_T","core_volume_mm3","al_nH_per_turn2"]}
        grid = ttk.Frame(tab, padding=10); grid.pack(fill="both", expand=True)
        labels=[("Ae [mm²]","ae_mm2"),("le [mm]","le_mm"),("Bmax [T]","bmax_T"),("Core volume [mm³]","core_volume_mm3"),("AL [nH/turn²] (opt)","al_nH_per_turn2")]
        for r,(lbl,k) in enumerate(labels):
            ttk.Label(grid, text=lbl).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=self.core_vars[k], width=20).grid(row=r, column=1, sticky="w", pady=3)
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
        self.mos_vars = {k: tk.StringVar(value=str(m.get(k,""))) for k in ["rds_on_mohm","rds_temp_C","rds_temp_coeff","tr_ns","tf_ns","coss_nF","qg_nC","vgate_V","k_sw_overlap"]}
        grid = ttk.Frame(tab, padding=10); grid.pack(fill="both", expand=True)
        labels=[("Rds_on [mΩ]","rds_on_mohm"),("Tj for Rds [°C]","rds_temp_C"),("Rds temp coeff [1/K]","rds_temp_coeff"),
                ("tr [ns]","tr_ns"),("tf [ns]","tf_ns"),("Coss [nF]","coss_nF"),("Qg [nC]","qg_nC"),("Vgate [V]","vgate_V"),("k_sw_overlap","k_sw_overlap")]
        for r,(lbl,k) in enumerate(labels):
            ttk.Label(grid, text=lbl).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=self.mos_vars[k], width=20).grid(row=r, column=1, sticky="w", pady=3)
    def build_stein_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Steinmetz")
        s = self.model["steinmetz"]
        self.st_vars = {k: tk.StringVar(value=str(s.get(k,""))) for k in ["k","alpha","beta"]}
        grid = ttk.Frame(tab, padding=10); grid.pack(fill="both", expand=True)
        for r,(lbl,k) in enumerate([("k","k"),("alpha","alpha"),("beta","beta")]):
            ttk.Label(grid, text=lbl).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=self.st_vars[k], width=20).grid(row=r, column=1, sticky="w", pady=3)
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
        ttk.Button(btns, text="Run sweep", command=self.run_sweep).pack(side="left", padx=5)
        ttk.Button(btns, text="Apply best K", command=self.apply_best).pack(side="left", padx=5)
        self.k_result = tk.Text(tab, height=16, wrap="none")
        self.k_result.pack(fill="both", expand=True, padx=8, pady=6)
    def build_library_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Core Library")
        top = ttk.Frame(tab, padding=6); top.pack(fill="x")
        ttk.Button(top, text="Load library...", command=self.load_library).pack(side="left")
        ttk.Button(top, text="Use selected", command=self.use_selected_core).pack(side="left", padx=6)
        ttk.Label(top, text="(double-click row to apply)").pack(side="left", padx=6)
        cols=("distributor","distributor_sku","vendor","series","size","material","Ae_mm2","le_mm","Ve_mm3","Aw_mm2","AL_nH_per_turn2_ungapped")
        self.core_tree = ttk.Treeview(tab, columns=cols, show="headings")
        for c in cols:
            self.core_tree.heading(c, text=c)
            w = 120 if c in ("distributor_sku","size") else 90
            if c in ("Ae_mm2","le_mm","Ve_mm3","Aw_mm2","AL_nH_per_turn2_ungapped"): w=110
            self.core_tree.column(c, width=w, anchor="center")
        self.core_tree.pack(fill="both", expand=True, padx=6, pady=6)
        self.core_tree.bind("<Double-1>", lambda e: self.use_selected_core())
        self.core_tree.bind("<Motion>", self.on_core_hover)
        self.tooltip=None
        if os.path.exists(LIB_DEFAULT):
            try:
                data = json.load(open(LIB_DEFAULT, "r", encoding="utf-8"))
                for it in data.get("cores", []):
                    self.core_tree.insert("", "end", values=[it.get(k,"") for k in cols])
            except Exception as e:
                messagebox.showwarning("Library", str(e))
    def on_core_hover(self, event):
        iid = self.core_tree.identify_row(event.y)
        if not iid:
            if self.tooltip: self.tooltip.destroy(); self.tooltip=None
            return
        vals = self.core_tree.item(iid, "values")
        text = ("Поставщик: %s\nАртикул: %s\nПроизводитель: %s\nСерия: %s  Размер: %s  Материал: %s\nAe= %s мм², le= %s мм, Ve= %s мм³, Aw= %s мм², AL≈ %s нГн/вит²" % (vals[0], vals[1], vals[2], vals[3], vals[4], vals[5], vals[6], vals[7], vals[8], vals[9], vals[10]))
        if self.tooltip: self.tooltip.destroy()
        self.tooltip = Tooltip(self.core_tree, text=text)
        x=self.core_tree.winfo_rootx()+event.x+20
        y=self.core_tree.winfo_rooty()+event.y+10
        self.tooltip.wm_geometry("+%d+%d"%(x,y))
    def use_selected_core(self):
        sel = self.core_tree.selection()
        if not sel: return
        vals = self.core_tree.item(sel[0], "values")
        mapping = {"ae_mm2": vals[6], "le_mm": vals[7], "al_nH_per_turn2": vals[10]}
        for k,v in mapping.items():
            if k in self.core_vars: self.core_vars[k].set(str(v))
        if vals[8]:
            self.core_vars["core_volume_mm3"].set(str(vals[8]))
    def build_results_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Results")
        top = ttk.Frame(tab, padding=6); top.pack(fill="x")
        ttk.Button(top, text="Compute", command=self.compute).pack(side="left", padx=4)
        ttk.Button(top, text="Save report...", command=self.save_report).pack(side="left", padx=4)
        self.res_text = tk.Text(tab, wrap="none", font=("Consolas", 10))
        self.res_text.pack(fill="both", expand=True)

    def build_waveforms_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Waveforms")
        self.fig = mplfig.Figure(figsize=(7,5))
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("t [s]")
        self.ax.set_ylabel("Value")
        self.canvas = FigureCanvasTkAgg(self.fig, master=tab)
        self.canvas.get_tk_widget().pack(side="left", fill="both", expand=True)
        ctrl = ttk.Frame(tab, padding=10); ctrl.pack(side="right", fill="y")
        self.chk_vars = {}
        self.chk_buttons_frame = ctrl

    def build_transformer_tab(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="Transformer")
        ttk.Label(tab, text="Edit turn counts and press Apply. Np is reference.").pack(anchor="w", padx=8, pady=4)
        self.tr_text = tk.Text(tab, height=8)
        self.tr_text.pack(fill="x", padx=8)
        ttk.Button(tab, text="Apply", command=self.apply_transformer).pack(anchor="e", padx=8, pady=6)
    def add_output(self):
        d = OutputDialog(self); self.wait_window(d)
        if d.result:
            self.model["outputs"].append(d.result)
            self.tree.insert("", "end", values=[d.result.get(c,"") for c in ("name","v","i","ripple_v","diode_drop","mlt_mm","qrr_nC")])
    def edit_output(self):
        sel = self.tree.selection()
        if not sel: return
        idx = self.tree.index(sel[0])
        data = self.model["outputs"][idx]
        d = OutputDialog(self, data=data); self.wait_window(d)
        if d.result:
            self.model["outputs"][idx] = d.result
            self.tree.item(sel[0], values=[d.result.get(c,"") for c in ("name","v","i","ripple_v","diode_drop","mlt_mm","qrr_nC")])
    def remove_output(self):
        sel = self.tree.selection()
        if not sel: return
        idx = self.tree.index(sel[0]); del self.model["outputs"][idx]; self.tree.delete(sel[0])
    def collect_cfg(self) -> Dict[str, Any]:
        inp = {k: v.get() for k,v in self.inputs_vars.items()}
        cin_vrip = inp.pop("cin_vrip","5.0")
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
        kopt = {k: v.get() for k,v in self.k_vars.items()}
        cfg = {"input": inp, "outputs": outs, "core": core, "geometry": geom, "rcd": rcd, "mosfet": mos, "steinmetz": st, "cin_vrip": cin_vrip, "k_optimize": kopt}
        return cfg
    def compute(self):
        if not HAVE_CORE:
            messagebox.showerror("Import error", "Cannot import flyback_design_v5.py\
"+IMPORT_ERR); return
        try:
            cfg = self.collect_cfg();
            cfg_norm = normalize_cfg(cfg)
            res = run(cfg_norm)
            self.show_results(res)
        except Exception as e:
            messagebox.showerror("Compute error", str(e))
    def run_sweep(self):
        try:
            cfg = self.collect_cfg()
            cfg_norm = normalize_cfg(cfg)
            fin = FlybackInput(**cfg_norm["input"])
            outs = [OutputSpec(**o) for o in cfg_norm["outputs"]]
            core = CoreParameters(**cfg_norm["core"])
            geom = Geometry(**cfg_norm["geometry"])
            stein = Steinmetz(**cfg_norm["steinmetz"]) if "steinmetz" in cfg_norm else None
            mos = MosfetParams(**cfg_norm["mosfet"]) if "mosfet" in cfg_norm else None
            rcd = RCDClamp(**cfg_norm["rcd"]) if "rcd" in cfg_norm else None
            crit = self.k_vars["criterion"].get()
            dmin=float(self.k_vars["dmin"].get()); dmax=float(self.k_vars["dmax"].get()); dstep=float(self.k_vars["dstep"].get())
            sweep = sweep_k(fin, outs, geom, core, rcd=rcd, stein=stein, mosfet=mos, criterion=crit, dmin=dmin, dmax=dmax, dstep=dstep, cin_vrip=cfg_norm.get("cin_vrip",5.0))
            lines = []
            lines.append(f"Criterion: {crit}")
            lines.append("D     Vref[V]   K_ideal  Vds[V]   Ipk[A]  VRRM_max[V]  Ploss[W]")
            for row in sweep["grid"]:
                lines.append(f"{row['D']:.3f}  {row['Vref']:.1f}  {row['K']:.3f}   {row['Vds']:.1f}   {row['Ipk']:.2f}   {row['VRRM_max']:.1f}     {row['Ploss']:.2f}")
            best = sweep["best"]
            lines.append("")
            lines.append(f"BEST: D={best['D']:.3f}")
            self.k_result.delete("1.0","end"); self.k_result.insert("1.0", "\n".join(lines))
            self.sweep_cache = sweep
        except Exception as e:
            messagebox.showerror("K-optimizer", str(e))
    def apply_best(self):
        if not hasattr(self, "sweep_cache"):
            messagebox.showinfo("K-optimizer", "Run sweep first."); return
        Dbest = self.sweep_cache["best"]["D"]
        self.inputs_vars["duty_max"].set(f"{Dbest:.4f}")
        messagebox.showinfo("K-optimizer", f"Применено: D(Vin_min)={Dbest:.3f}. Пересчитайте (Compute).")
    def load_library(self):
        path = filedialog.askopenfilename(filetypes=[("JSON","*.json"),("All","*.*")], initialfile=LIB_DEFAULT)
        if not path: return
        try:
            data = json.load(open(path,"r",encoding="utf-8"))
            for iid in self.core_tree.get_children():
                self.core_tree.delete(iid)
            for it in data.get("cores", []):
                vals = [it.get(k,"") for k in ("distributor","distributor_sku","vendor","series","size","material","Ae_mm2","le_mm","Ve_mm3","Aw_mm2","AL_nH_per_turn2_ungapped")]
                self.core_tree.insert("", "end", values=vals)
        except Exception as e:
            messagebox.showerror("Library", str(e))
    def show_results(self, res: Dict[str, Any]):
        self.res_text.delete("1.0","end")
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
        lines.append(f"Vref = {ini['vref_V']:.2f} V")
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
            if r.get('rcd'):
                rc = r['rcd']
                lines.append(f"RCD: Llk={rc['Llk_H']:.3e} H, Vclamp={rc['Vclamp_V']:.1f} V")
                lines.append(f"     Csnub={rc['C_snub_F']:.3e} F, Rsnub={rc['R_snub_Ohm']:.1f} Ω, tau={rc['tau_s']:.3e} s")
            lines.append("")
            lines.append("--- ПРОВОДНИКИ ---")
            lines.append(f"A_cu_primary = {r['wires']['primary_area_mm2']:.6f} мм^2; d_eq = {r['wires']['primary_dia_mm']:.3f} мм; strands = {int(r['wires']['primary_strands'])}")
            for o in res["outputs"]:
                name = o["name"]
                lines.append(f"A_cu_sec[{name}] = {r['wires'][name+'_area_mm2']:.6f} мм^2; d_eq = {r['wires'][name+'_dia_mm']:.3f} мм; strands = {int(r['wires'][name+'_strands'])}")
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

        if "waveforms" in res:
            self.plot_waveforms(res["waveforms"])
            self.populate_transformer(res)
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
            self.model = cfg
            for w in self.nb.winfo_children(): w.destroy()
            self.build_inputs_tab(); self.build_outputs_tab(); self.build_core_tab()
            self.build_geom_tab(); self.build_clamp_tab(); self.build_mosfet_tab(); self.build_stein_tab(); self.build_k_tab(); self.build_library_tab(); self.build_waveforms_tab(); self.build_transformer_tab(); self.build_results_tab()
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

    def plot_waveforms(self, wf: Dict[str, Any]):
        self.ax.clear()
        for child in self.chk_buttons_frame.winfo_children():
            child.destroy()
        self.chk_vars.clear()
        lines = {}
        for name,(t,val) in wf.items():
            line, = self.ax.plot(t, val, label=name)
            lines[name] = line
        self.ax.legend()
        for name,line in lines.items():
            var = tk.BooleanVar(value=True)
            def cmd(l=line, v=var):
                l.set_visible(v.get()); self.canvas.draw()
            chk = ttk.Checkbutton(self.chk_buttons_frame, text=name, variable=var, command=cmd)
            chk.pack(anchor="w")
            self.chk_vars[name] = var
        self.canvas.draw()

    def populate_transformer(self, res: Dict[str, Any]):
        if "refined" not in res:
            return
        r = res["refined"]
        np_t = r["np_turns"]
        txt = f"Np = {np_t}\n"
        for name, ns in r["ns_turns"].items():
            txt += f"Ns_{name} = {ns}\n"
        self.tr_text.delete("1.0","end")
        self.tr_text.insert("1.0", txt)

    def apply_transformer(self):
        data = self.tr_text.get("1.0","end").strip().splitlines()
        if not data:
            return
        try:
            np_t = int(data[0].split("=")[1])
            ns = [int(l.split("=")[1]) for l in data[1:]]
        except Exception:
            messagebox.showerror("Error","Bad turns format")
            return
        cfg = self.collect_cfg()
        cfg["turns_override"] = {"np": np_t, "ns": {cfg["outputs"][i]["name"]: ns[i] for i in range(len(ns))}}
        cfg_norm = normalize_cfg(cfg)
        try:
            res = run(cfg_norm)
            self.show_results(res)
        except Exception as e:
            messagebox.showerror("Error", str(e))
if __name__ == "__main__":
    app = App(); app.mainloop()