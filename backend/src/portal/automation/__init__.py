"""Moteur de règles déterministes : sonde → condition → action sur événements."""

from .engine import AutomationError, run_rules
from .models import Condition, PrimitiveCall, Rule

__all__ = ["AutomationError", "Condition", "PrimitiveCall", "Rule", "run_rules"]
