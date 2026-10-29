# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Charm patterns: pattern number -> $KeychainSeed -> shader parameters.

Every CS2 charm has a pattern (template) number between 0 and 100000. The
materials read it as ``$KeychainSeed`` in their DynamicParams. Valve does
not document the conversion; ``seed = pattern / 100000`` matches the game's
behaviour as far as it can be checked (e.g. Butane Buddy: the fluid color
cycles once over the whole range, the fill level every 1000 patterns,
see ``frac($KeychainSeed*100)``). Pure Python, no bpy.
"""

import random

from . import expr

PATTERN_MAX = 100000
SEED_VAR = "$KeychainSeed"

# Runtime inputs other than the seed, at rest: no weapon shake, liquid
# surface pointing up. Expressions that use them get these values.
REST_ENV = {
    "$ent_weapon_shake": (0.0, 0.0, 0.0),
    "$bone_upvector$liquid_surface": (0.0, 0.0, 1.0),
}


def seed_from_pattern(pattern):
    pattern = min(max(int(pattern), 0), PATTERN_MAX)
    return pattern / PATTERN_MAX


def random_pattern(rng=None):
    return (rng or random).randint(0, PATTERN_MAX)


def uses_seed(expression):
    try:
        return SEED_VAR in expr.variables_used(expression)
    except expr.ExprError:
        return False


def seed_params(dynamic):
    """Names of the dynamic parameters that depend on the pattern."""
    return sorted(name for name, text in dynamic.items() if uses_seed(text))


def evaluate_dynamic(dynamic, pattern, only_seed=True):
    """Evaluate DynamicParams for a pattern.

    Returns ``(values, errors)``: ``values`` maps parameter names to floats
    or tuples, ``errors`` maps names to messages for expressions that could
    not be evaluated (those keep their static value). With ``only_seed``
    expressions that do not depend on the pattern are skipped: they drive
    runtime effects (weapon shake, sloshing) and the static vmat value is
    the better rest value.
    """
    env = dict(REST_ENV)
    env[SEED_VAR] = seed_from_pattern(pattern)
    values, errors = {}, {}
    for name, text in dynamic.items():
        if only_seed and not uses_seed(text):
            continue
        try:
            values[name] = expr.evaluate(text, env)
        except expr.ExprError as exc:
            errors[name] = str(exc)
    return values, errors
