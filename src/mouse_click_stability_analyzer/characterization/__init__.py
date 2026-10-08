"""Offline Schedule Association Window characterization (4E-B1).

This package does not choose a window policy and is not a DUT verdict path.
Configured Interval Range (Stage 2D) is not an input.
"""
from __future__ import annotations

ANALYSIS_CONTRACT = "MCSA_CHARACTERIZATION_V1"
RESIDUAL_CONVENTION = "nearest_nominal_slot_half_open"

__all__ = ["ANALYSIS_CONTRACT", "RESIDUAL_CONVENTION"]
