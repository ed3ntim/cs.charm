# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Evaluator for the ``DynamicParams`` expressions of CS2 materials.

CS2 charm materials compute some shader parameters per item, e.g. the
Butane Buddy liquid:

    "g_flLiquidLevelHeight"  "return lerp(.45,.8,frac($KeychainSeed*100));"

The language is a small HLSL subset: numbers, ``$variables`` (with
swizzles like ``$ent_weapon_shake.x``), local variables (``v0 = ...;``),
``return``, arithmetic, comparisons, ``&&``/``||``, the ternary operator
and a handful of intrinsics (lerp, pow, frac, clamp, ...). Vectors are
tuples; operators work component-wise and broadcast scalars, like HLSL.

No ``eval()``: expressions come from game files and user libraries, so
they are tokenized and interpreted here. Escaped line breaks (backslash +
n, as stored in .vmat strings) count as whitespace. Pure Python, no bpy.
"""

import math
import re

__all__ = ("ExprError", "evaluate", "variables_used")


class ExprError(ValueError):
    """Raised for expressions that cannot be parsed or evaluated."""


_TOKEN = re.compile(r"""
    (?P<ws>\s+|//[^\n]*|\\[nrt])
  | (?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<var>\$[A-Za-z_][A-Za-z0-9_$]*)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>&&|\|\||==|!=|<=|>=|[-+*/%<>?:(),;=.!])
""", re.VERBOSE)


def _tokenize(text):
    pos, out = 0, []
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            raise ExprError(f"unexpected character {text[pos]!r} at {pos}")
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group(kind)))
    out.append(("end", ""))
    return out


# ---------------------------------------------------------------------------
# Values: float or tuple of floats
# ---------------------------------------------------------------------------

def _broadcast(a, b):
    if isinstance(a, tuple) or isinstance(b, tuple):
        n = max(len(x) for x in (a, b) if isinstance(x, tuple))
        a = a if isinstance(a, tuple) else (a,) * n
        b = b if isinstance(b, tuple) else (b,) * n
        n = min(len(a), len(b))  # HLSL truncates to the smaller vector
        return a[:n], b[:n]
    return a, b


def _map(fn, *args):
    """Apply a scalar function component-wise with broadcasting."""
    if not any(isinstance(a, tuple) for a in args):
        return float(fn(*args))
    n = min(len(a) for a in args if isinstance(a, tuple))
    cols = [a if isinstance(a, tuple) else (a,) * n for a in args]
    return tuple(float(fn(*vals)) for vals in zip(*(c[:n] for c in cols)))


def _truthy(v):
    return any(x != 0 for x in v) if isinstance(v, tuple) else v != 0


def _pow(a, b):
    try:
        return math.pow(a, b)
    except (ValueError, OverflowError):
        return 0.0  # HLSL returns NaN for negative bases; 0 is a safe stand-in


def _div(a, b):
    return a / b if b != 0 else 0.0


def _fmod(a, b):
    return math.fmod(a, b) if b != 0 else 0.0


def _smoothstep(e0, e1, x):
    t = min(max(_div(x - e0, e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def _vector(n):
    def make(*args):
        flat = []
        for a in args:
            flat.extend(a if isinstance(a, tuple) else (a,))
        if len(flat) == 1:
            flat *= n
        if len(flat) != n:
            raise ExprError(f"float{n} needs {n} components, got {len(flat)}")
        return tuple(float(x) for x in flat)
    return make


def _dot(a, b):
    a, b = _broadcast(a, b)
    if not isinstance(a, tuple):
        return a * b
    return sum(x * y for x, y in zip(a, b))


def _length(a):
    return math.sqrt(_dot(a, a))


_FUNCS = {
    "lerp": lambda a, b, t: _map(lambda x, y, s: x + (y - x) * s, a, b, t),
    "pow": lambda a, b: _map(_pow, a, b),
    "frac": lambda a: _map(lambda x: x - math.floor(x), a),
    "abs": lambda a: _map(abs, a),
    "sin": lambda a: _map(math.sin, a),
    "cos": lambda a: _map(math.cos, a),
    "tan": lambda a: _map(math.tan, a),
    "sqrt": lambda a: _map(lambda x: math.sqrt(x) if x >= 0 else 0.0, a),
    "floor": lambda a: _map(math.floor, a),
    "ceil": lambda a: _map(math.ceil, a),
    "round": lambda a: _map(lambda x: math.floor(x + 0.5), a),
    "sign": lambda a: _map(lambda x: (x > 0) - (x < 0), a),
    "min": lambda a, b: _map(min, a, b),
    "max": lambda a, b: _map(max, a, b),
    "clamp": lambda a, lo, hi: _map(lambda x, l, h: min(max(x, l), h), a, lo, hi),
    "saturate": lambda a: _map(lambda x: min(max(x, 0.0), 1.0), a),
    "step": lambda e, x: _map(lambda y, z: 1.0 if z >= y else 0.0, e, x),
    "smoothstep": lambda e0, e1, x: _map(_smoothstep, e0, e1, x),
    "fmod": lambda a, b: _map(_fmod, a, b),
    "exp": lambda a: _map(lambda x: math.exp(min(x, 700)), a),
    "log": lambda a: _map(lambda x: math.log(x) if x > 0 else 0.0, a),
    "dot": _dot,
    "length": _length,
    "float": _vector(1),
    "float2": _vector(2),
    "float3": _vector(3),
    "float4": _vector(4),
}
_FUNCS["float"] = lambda a: a[0] if isinstance(a, tuple) else float(a)

_SWIZZLE = {"x": 0, "y": 1, "z": 2, "w": 3, "r": 0, "g": 1, "b": 2, "a": 3}


def _swizzle(value, names):
    if any(c not in _SWIZZLE for c in names):
        raise ExprError(f"bad swizzle .{names}")
    vec = value if isinstance(value, tuple) else (value,)
    idx = [_SWIZZLE[c] for c in names]
    if max(idx) >= len(vec):
        if not isinstance(value, tuple):
            vec = (value,) * 4  # scalar.xxx broadcasts
        else:
            vec = vec + (0.0,) * (max(idx) + 1 - len(vec))
    out = tuple(vec[i] for i in idx)
    return out[0] if len(out) == 1 else out


# ---------------------------------------------------------------------------
# Parser / interpreter (precedence climbing, evaluates while parsing)
# ---------------------------------------------------------------------------

_BINARY = {
    "||": (1, lambda a, b: float(_truthy(a) or _truthy(b))),
    "&&": (2, lambda a, b: float(_truthy(a) and _truthy(b))),
    "==": (3, lambda a, b: _map(lambda x, y: float(x == y), a, b)),
    "!=": (3, lambda a, b: _map(lambda x, y: float(x != y), a, b)),
    "<": (4, lambda a, b: _map(lambda x, y: float(x < y), a, b)),
    ">": (4, lambda a, b: _map(lambda x, y: float(x > y), a, b)),
    "<=": (4, lambda a, b: _map(lambda x, y: float(x <= y), a, b)),
    ">=": (4, lambda a, b: _map(lambda x, y: float(x >= y), a, b)),
    "+": (5, lambda a, b: _map(lambda x, y: x + y, a, b)),
    "-": (5, lambda a, b: _map(lambda x, y: x - y, a, b)),
    "*": (6, lambda a, b: _map(lambda x, y: x * y, a, b)),
    "/": (6, lambda a, b: _map(_div, a, b)),
    "%": (6, lambda a, b: _map(_fmod, a, b)),
}


class _Interpreter:
    def __init__(self, tokens, env, default):
        self.tokens = tokens
        self.i = 0
        self.env = env
        self.default = default
        self.locals = {}

    # -- token helpers ---------------------------------------------------------

    def peek(self, offset=0):
        return self.tokens[min(self.i + offset, len(self.tokens) - 1)]

    def take(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, value):
        kind, tok = self.take()
        if tok != value:
            raise ExprError(f"expected {value!r}, got {tok or kind!r}")

    # -- statements --------------------------------------------------------------

    def run(self):
        result = None
        while self.peek()[0] != "end":
            kind, tok = self.peek()
            if tok == ";":
                self.take()
                continue
            if kind == "name" and tok == "return":
                self.take()
                result = self.expression()
                break
            if kind == "name" and self.peek(1)[1] == "=" and self.peek(2)[1] != "=":
                self.take()
                self.take()
                self.locals[tok] = self.expression()
                continue
            result = self.expression()  # bare expression: last one wins
        if result is None:
            raise ExprError("expression has no value")
        return result

    # -- expressions -------------------------------------------------------------

    def expression(self):
        cond = self.binary(1)
        if self.peek()[1] == "?":
            self.take()
            a = self.expression()
            self.expect(":")
            b = self.expression()
            return a if _truthy(cond) else b
        return cond

    def binary(self, min_prec):
        left = self.unary()
        while True:
            op = self.peek()[1]
            entry = _BINARY.get(op) if self.peek()[0] == "op" else None
            if entry is None or entry[0] < min_prec:
                return left
            self.take()
            right = self.binary(entry[0] + 1)
            left = entry[1](left, right)

    def unary(self):
        tok = self.peek()[1]
        if self.peek()[0] == "op" and tok in ("-", "+", "!"):
            self.take()
            value = self.unary()
            if tok == "-":
                return _map(lambda x: -x, value)
            if tok == "!":
                return float(not _truthy(value))
            return value
        return self.postfix(self.primary())

    def postfix(self, value):
        while self.peek()[1] == "." and self.peek(1)[0] == "name":
            self.take()
            value = _swizzle(value, self.take()[1])
        return value

    def primary(self):
        kind, tok = self.take()
        if kind == "num":
            return float(tok)
        if kind == "var":
            return self.variable(tok)
        if kind == "name":
            if tok == "exists" and self.peek()[1] == "(":
                return self.exists()
            if self.peek()[1] == "(":
                return self.call(tok)
            if tok in self.locals:
                return self.locals[tok]
            if tok in ("true", "false"):
                return float(tok == "true")
            raise ExprError(f"unknown name {tok!r}")
        if tok == "(":
            value = self.expression()
            self.expect(")")
            return value
        raise ExprError(f"unexpected {tok or kind!r}")

    def variable(self, name):
        if name in self.env:
            value = self.env[name]
        elif name.lower() in self.env:
            value = self.env[name.lower()]
        else:
            value = self.default
        return tuple(float(v) for v in value) if isinstance(value, (tuple, list)) else float(value)

    def exists(self):
        """exists($var): 1 if the variable is provided, else 0."""
        self.expect("(")
        kind, tok = self.take()
        if kind != "var":
            raise ExprError("exists() takes a $variable")
        self.expect(")")
        return float(tok in self.env or tok.lower() in self.env)

    def call(self, name):
        fn = _FUNCS.get(name.lower())
        if fn is None:
            raise ExprError(f"unknown function {name!r}")
        self.expect("(")
        args = []
        if self.peek()[1] != ")":
            args.append(self.expression())
            while self.peek()[1] == ",":
                self.take()
                args.append(self.expression())
        self.expect(")")
        try:
            return fn(*args)
        except TypeError as exc:
            raise ExprError(f"{name}: {exc}") from None


def evaluate(text, env=None, default=0.0):
    """Evaluate a DynamicParams expression.

    ``env`` maps variable names (with ``$``) to floats or tuples; unknown
    variables evaluate to ``default``. Returns a float or a tuple.
    """
    return _Interpreter(_tokenize(text), env or {}, default).run()


def variables_used(text):
    """Set of ``$variables`` referenced by an expression."""
    return {tok for kind, tok in _tokenize(text) if kind == "var"}
