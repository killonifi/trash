
# Flyback Calculator GUI — v7

A concise yet complete multi‑output flyback converter design helper.

## Quick start

```bash
python flyback_gui.py
```

The GUI consists of four tabs:

| Tab            | Purpose                                                         |
|----------------|-----------------------------------------------------------------|
| *Inputs*       | Enter Vin range, fsw, and an arbitrary number of output rails.  |
| *Results*      | JSON dump of key parameters (D, Ipk, Lp, RCD snubber, …).       |
| *Waveforms*    | Plots of primary and secondary currents/voltages with check‑boxes to toggle each trace. |
| *Transformer*  | Shows turns ratio (Np=1) and lets you experiment with turn counts (β‑version). |

## Theory and equations

Full derivation is beyond a README; essentials:

* **Energy per cycle**  
  \( E = P / (\eta f_\text{sw}) \)

* **Primary inductance**  
  \( L_p = 2E / I_\text{pk}^2 \)

* **Peak current (DCM)**  
  \( I_\text{pk} = \dfrac{2P}{V_{\text{in,min}} D} \)

* **Turns ratio** (volt‑second balance)  
  \( \dfrac{N_s}{N_p} =
     \dfrac{V_{\text{out}}}{V_{\text{in,min}} D / (1 - D)} \)

* **Steinmetz losses** not included in this lightweight core; see IEC 60404‑8‑4.

All symbols are defined in the table at the top of *results* panel.

## Tests

`tests.py` runs ten synthetic multi‑output cases covering:

* Vin 36–75 V, 85–265 VAC, 250–450 VDC
* Loads 3–60 W over one to four secondaries
* fsw 40–130 kHz  
and checks that:

* `FlybackCore` returns without exceptions
* `Ipk` stays finite and matches optimisation criterion
* RCD snubber numbers are populated when leakage enabled

All ten pass.

---

© 2025 Д. (Дима) — MIT License
