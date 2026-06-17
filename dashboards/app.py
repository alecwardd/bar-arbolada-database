"""
Bar Arbolada Analytics - Streamlit entry point.

Run with: streamlit run dashboards/app.py

Delegates to Home.py so the README command works and pages/ are discovered correctly.
"""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parent / "Home.py"), run_name="__main__")
