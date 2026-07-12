"""Moteur de règles déterministes : sonde → condition → action sur événements.

Les règles sont écrites par l'utilisateur (bloc Rules de l'UI), stockées en
base (user_rules) et exécutées par l'écouteur générique de runtime.py.
"""

from .engine import AutomationError, run_rule, run_rules
from .models import Condition, PrimitiveCall, Rule

__all__ = ["AutomationError", "Condition", "PrimitiveCall", "Rule", "run_rule", "run_rules"]
