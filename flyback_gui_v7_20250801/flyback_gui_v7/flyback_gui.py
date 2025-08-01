
"""flyback_gui.py
Simple Tkinter GUI wrapper around flyback_core.FlybackCore.

Run:
    python flyback_gui.py
"""

import tkinter as tk
from tkinter import ttk, messagebox

from flyback_core import FlybackCore
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.figure as mplfig
import json
import re

__version__ = "v7.1.0"


class FlybackGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Flyback Calculator {__version__}")
        self.geometry("1080x720")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self._init_inputs_tab()
        self._init_results_tab()
        self._init_waveforms_tab()
        self._init_transformer_tab()

        self.core = None  # FlybackCore instance
        self.trans_ratio = []  # Ns/Np list

    # ------------------------------------------------------------------ #
    def _init_inputs_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Inputs")

        frm = ttk.Frame(tab, padding=10)
        frm.pack(anchor=tk.NW, fill=tk.X)

        def _label(row, text):
            ttk.Label(frm, text=text).grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)

        def _entry(row, var):
            ent = ttk.Entry(frm, textvariable=var, width=15)
            ent.grid(row=row, column=1, sticky=tk.W, padx=5, pady=2)
            return ent

        self.vin_min_var = tk.DoubleVar(value=85.0)
        self.vin_max_var = tk.DoubleVar(value=265.0)
        self.fsw_var = tk.DoubleVar(value=100e3)

        _label(0, "Vin_min [V]:")
        _entry(0, self.vin_min_var)
        _label(1, "Vin_max [V]:")
        _entry(1, self.vin_max_var)
        _label(2, "fsw [Hz]:")
        _entry(2, self.fsw_var)

        # Outputs listbox
        out_frame = ttk.LabelFrame(frm, text="Outputs (V, A)")
        out_frame.grid(row=0, column=2, rowspan=3, padx=15, pady=2, sticky=tk.N)

        self.outputs_box = tk.Text(out_frame, width=25, height=6)
        self.outputs_box.insert(
            tk.END, "5 2\n12 1.2\n-12 0.3"
        )  # default 3 rails
        self.outputs_box.pack()

        calc_btn = ttk.Button(frm, text="Calculate", command=self.calculate)
        calc_btn.grid(row=3, column=0, columnspan=2, pady=10)

    # ------------------------------------------------------------------ #
    def _init_results_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Results")
        self.results_text = tk.Text(tab, wrap=tk.NONE)
        self.results_text.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------ #
    def _init_waveforms_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Waveforms")

        self.fig = mplfig.Figure(figsize=(7, 5))
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("t [s]")
        self.ax.set_ylabel("Current [A]")

        self.canvas = FigureCanvasTkAgg(self.fig, master=tab)
        self.canvas.get_tk_widget().pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Controls
        ctrl = ttk.Frame(tab, padding=10)
        ctrl.pack(side=tk.RIGHT, fill=tk.Y)

        self.chk_vars = {}
        self.chk_buttons_frame = ctrl

    # ------------------------------------------------------------------ #
    def _init_transformer_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Transformer")

        info = ttk.Label(
            tab,
            text=(
                "Edit turn counts and press [Apply].  "
                "Np is the reference (integer >0).  Each Ns must be integer."
            ),
        )
        info.pack(anchor=tk.NW, pady=5, padx=10)

        self.transformer_text = tk.Text(tab, height=8)
        self.transformer_text.pack(fill=tk.X, padx=10)

        btn = ttk.Button(tab, text="Apply", command=self.apply_transformer)
        btn.pack(pady=6, padx=10, anchor=tk.E)

    # ------------------------------------------------------------------ #
    def calculate(self):
        try:
            vin_min = float(self.vin_min_var.get())
            vin_max = float(self.vin_max_var.get())
            fsw = float(self.fsw_var.get())
        except ValueError:
            messagebox.showerror("Input error", "Input voltages and fsw must be numbers")
            return

        # Parse outputs
        Vouts = []
        Iouts = []
        for line in self.outputs_box.get("1.0", tk.END).strip().splitlines():
            parts = re.split(r"[ ,;\t]+", line.strip())
            if len(parts) != 2:
                continue
            try:
                v, i = map(float, parts)
            except ValueError:
                continue
            Vouts.append(abs(v))
            Iouts.append(abs(i))

        if not Vouts:
            messagebox.showerror("Input error", "Specify at least one output voltage/current pair")
            return

        try:
            self.core = FlybackCore(vin_min, vin_max, Vouts, Iouts, fsw)
        except Exception as e:
            messagebox.showerror("Calculation error", str(e))
            return

        res = self.core.result
        self.trans_ratio = [
            vo / (res["Vin_min"] * res["D"] / (1 - res["D"])) for vo in Vouts
        ]
        self._populate_results(res)
        self._plot_waveforms(res["waveforms"])
        self._populate_transformer(res)

        self.notebook.select(1)  # switch to Results tab

    # ------------------------------------------------------------------ #
    def _populate_results(self, res):
        txt = json.dumps({k: v for k, v in res.items() if k != "waveforms"}, indent=2)
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert(tk.END, txt)

    # ------------------------------------------------------------------ #
    def _plot_waveforms(self, wfs):
        self.ax.clear()
        self.ax.set_xlabel("t [s]")
        self.ax.set_ylabel("Current [A]")

        # Clear previous checkboxes
        for child in self.chk_buttons_frame.winfo_children():
            child.destroy()
        self.chk_vars.clear()

        lines = {}
        for name, (t, i) in wfs.items():
            line, = self.ax.plot(t, i, label=name)
            lines[name] = line

        self.ax.legend()

        # Checkbox controls
        for idx, name in enumerate(wfs.keys()):
            var = tk.BooleanVar(value=True)
            def _make_cmd(line=lines[name], v=var):
                return lambda: (line.set_visible(v.get()), self.canvas.draw())
            chk = ttk.Checkbutton(
                self.chk_buttons_frame,
                text=name,
                variable=var,
                command=_make_cmd(),
            )
            chk.pack(anchor=tk.W)
            self.chk_vars[name] = var

        self.canvas.draw()

    # ------------------------------------------------------------------ #
    def _populate_transformer(self, res):
        txt = "Np = 100\n"
        for k, n in enumerate(self.trans_ratio, 1):
            txt += f"Ns{k} = {n*100:.0f}\n"
        self.transformer_text.delete("1.0", tk.END)
        self.transformer_text.insert(tk.END, txt)

    # ------------------------------------------------------------------ #
    def apply_transformer(self):
        if not self.core:
            messagebox.showinfo("Info", "Run calculation first.")
            return

        lines = self.transformer_text.get("1.0", tk.END).strip().splitlines()
        try:
            Np = int(lines[0].split("=")[1])
            Ns = [int(l.split("=")[1]) for l in lines[1:]]
            if Np <= 0 or any(n <= 0 for n in Ns):
                raise ValueError
        except Exception:
            messagebox.showerror("Error", "Turn counts must be positive integers.")
            return

        # Update Vouts according to new turns (keeping duty D unchanged)
        res = self.core.result
        D = res["D"]
        Vin_min = res["Vin_min"]

        new_Vouts = [Vin_min * D / (1 - D) * n / Np for n in Ns]
        Vouts = new_Vouts
        Iouts = self.core.Iouts  # keep loads

        try:
            self.core = FlybackCore(Vin_min, res["Vin_max"], Vouts, Iouts, res["fsw"])
        except Exception as e:
            messagebox.showerror("Recalc error", str(e))
            return

        res = self.core.result
        self._populate_results(res)
        self._plot_waveforms(res["waveforms"])

        messagebox.showinfo(
            "Recalculated",
            "Parameters updated using new turn counts.",
        )

# ------------------------------------------------------------------------- #

def main():
    app = FlybackGUI()
    app.mainloop()

if __name__ == "__main__":
    main()
