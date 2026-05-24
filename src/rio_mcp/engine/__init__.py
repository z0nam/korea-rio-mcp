"""Region-agnostic RIO computation engine.

Ported and generalized from the 26p17 Seogwipo project
(``src/io_analysis/compute_rio_single.py`` and ``extract_induce_coefficients.py``).
The Jeju-specific column names (``_jeju`` / ``_outside``) are generalized to
``_in_region`` / ``_out_region`` so the same engine serves any region.
"""
