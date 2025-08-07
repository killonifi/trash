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
             forward_design.py         # forward converter
             two_switch_forward_design.py # two-switch forward calculations
             half_bridge_design.py     # placeholder for half-bridge converter
             full_bridge_design.py     # placeholder for full-bridge converter
        ui/
            main_gui.py           # Tkinter GUI with topology selector
        data/
            core_library.json
            mosfet_library.json

Flyback, forward and two-switch forward topologies are implemented. Other
modules are stubs prepared for future expansion.

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