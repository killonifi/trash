Converter Design Tool
=====================

This project provides a modular toolkit for designing switch-mode power converters.
The calculation logic for each topology is placed in its own module so new
converters can be added with minimal changes.  The GUI offers a topology selector
and uses the corresponding calculation module.

Current structure::

    converter_tool/
        calculations/
            base.py               # common ConverterDesign interface
             flyback_design.py         # flyback calculations
             two_switch_flyback_design.py # two-switch flyback calculations
             forward_design.py         # forward converter
             two_switch_forward_design.py # two-switch forward calculations
             half_bridge_design.py     # placeholder for half-bridge converter
             full_bridge_design.py     # placeholder for full-bridge converter
        ui/
            main_gui.py           # Tkinter GUI with topology selector
        data/
            core_library.json
            mosfet_library.json

Flyback, two-switch flyback, forward and two-switch forward topologies are
implemented. Other modules are stubs prepared for future expansion.

Run the GUI:

```
python -m converter_tool.ui.main_gui
```

### ChatGPT integration

The UI can open a separate **ChatGPT** window from the toolbar. Enter your
OpenAI API key and you can chat with ChatGPT about the current design. The
assistant receives the values from all tabs (Inputs, Outputs, Core, Geometry,
MOSFET, etc.) and can suggest changes. Suggested field modifications are only
applied after user confirmation. Libraries for cores and MOSFETs are also
available to the model in the context.

### Undo/Redo

Buttons on the top bar allow undo and redo of most field edits and output
operations, providing a convenient way to revert accidental changes.

## 2‑Switch Flyback specifics (this update)

The module `converter_tool/calculations/two_switch_flyback_design.py` implements a **classic two‑switch flyback** (2T)
with a DCM‑first design flow reusing the proven magnetics pipeline from the single‑switch flyback and
adjusting **device stresses and losses**:

- **VDS requirement** per MOSFET is clamped to ≈ `Vin_max` (plus margin), not `Vin_max + K·(Vout+Vf)`.  
  This follows the well‑known characteristic of the classic 2T flyback where clamp diodes return leakage energy to the input.
- **MOSFET losses** account for *two* devices (conduction, switching overlap, Coss and gate drive).
- **Diode VRRM** on each secondary is computed similarly to the single‑switch case with the actual turns ratio.
- **Duty limit** is enforced at `< 0.5` as typical for 2T operation.

The GUI K‑optimizer works for the 2T module as well. It scans `D(Vin_min)` within `[dmin..dmax]` (capped at 0.49),
recomputes magnetics and then evaluates the chosen criterion after applying the 2T stresses.

**Notes / Roadmap**

- The paper “Двухключевой обратноходовой DC/DC‑преобразователь… с рекуперативным демпфером” (Силовая электроника №4, 2018)
  is included in the project folder and will be used to add the *soft‑switching regenerative snubber* option
  (with its specific expression for the MOSFET VDS ≈ (Vi + Vp)/2 and sizing of Cs/Ls). For now, the module implements the
  classic hard‑switched 2T variant with energy returned to the input by clamp diodes.
- If you enable `force_dcm=False` in JSON, the magnetics refinement loop from the base flyback will allow CCM, but the
  two‑switch VDS rule still applies.

**Key references used**

- TI Application Report *Designing a Two‑Switch Flyback Converter* (SLUA560/SLUA668 family).  
- ON Semiconductor / Onsemi AN‑4147 *Two‑Switch Flyback Converter Design*.  
- Article: «Двухключевой обратноходовой DC/DC‑преобразователь с широким диапазоном входного напряжения и рекуперативным демпфером», Силовая электроника №4, 2018.



### New: Improved 2‑Switch Flyback (regenerative soft‑switch)

- In the **Inputs** tab, when the selected topology is *2‑Switch Flyback*, a checkbox **“Improved 2T (regenerative soft‑switch)”** appears.  
  When enabled, the main image switches to the improved schematic and the calculator assumes ZVS with regenerative clamping:
  - switching and Coss losses of the MOSFETs are set to ~0 (first‑order);
  - the duty‑cycle cap is relaxed above 0.5 (you may scan up to ~0.8 in K‑optimizer).
- This mode is based on the article *«Двухключевой обратноходовой DC/DC‑преобразователь с широким диапазоном входного напряжения и рекуперативным демпфером»* (Силовая электроника №4, 2018), stored under `docs/`. Equations (6)–(9) describe the resonant behavior `ωs=1/sqrt(Ls·Cs)`, `Zs=sqrt(Ls/Cs)` and the recovery current through DP. The next iteration will include explicit sizing of `Ls` and `Cs` from the timing constraints.

Artwork:
- `Images/Two_switch_flyback_classic_user.png` — classic 2T flyback (your screenshot).
- `Images/Two_switch_flyback_regen.png` — improved 2T flyback with Cs1/Cs2, Ls1/Ls2, DP (schematic sketch for the UI).
