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
            flyback_design.py     # flyback calculations
            forward_design.py     # placeholder for forward converter
            half_bridge_design.py # placeholder for half-bridge converter
            full_bridge_design.py # placeholder for full-bridge converter
        ui/
            main_gui.py           # Tkinter GUI with topology selector
        data/
            core_library.json
            mosfet_library.json

Only the flyback topology is fully implemented at this time. Other modules are
stubs prepared for future expansion.

Run the GUI:

```
python -m converter_tool.ui.main_gui
```