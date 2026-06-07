"""
reactor_plotter.py
------------------
Entry point for the Reactor Pressure Analyzer.

Module layout
-------------
sequence_utils.py  -- valve sequence parsing and phase-bin computation
data_parser.py     -- streaming NDJSON file reader
plot_utils.py      -- matplotlib figure building and batch saving
gui.py             -- tkinter ReactorApp window
reactor_plotter.py -- this file; launch the app
"""

from gui import ReactorApp

if __name__ == "__main__":
    app = ReactorApp()
    app.mainloop()
