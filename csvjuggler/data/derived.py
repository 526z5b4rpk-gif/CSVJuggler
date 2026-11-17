"""Derived series: restricted formulas over existing series.

A formula such as ``a / b``, ``derivative(a)``, ``lowpass(a, 5)`` or ``integral(a - 2 * b)``
is parsed with :mod:`ast` and checked against a whitelist (numbers, variables, arithmetic,
comparisons and a few functions). It is then evaluated by walking the tree ourselves:
there is no ``eval`` of user text.

All variables are resampled (linear interpolation) on the X vector of the first variable
of the formula; the result is a series on that X vector.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, fields
from typing import Any

import numpy as np

from csvjuggler.data.series import Series

DERIVED_ALIAS = "calc"
"""Alias of the virtual dataset holding the derived series (reserved)."""

Value = np.ndarray | float


class FormulaError(Exception):
    """Invalid or non-computable formula (message in French, shown to the user)."""


@dataclass
class DerivedSeriesConfig:
    name: str
    formula: str
    variables: dict[str, str] = field(default_factory=dict)
    """Variable name in the formula → series id."""
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DerivedSeriesConfig:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    @property
    def series_id(self) -> str:
        return f"{DERIVED_ALIAS}/{self.name}"


# --------------------------------------------------------------------------- functions


def derivative(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    if len(y) < 2:
        return np.full_like(y, np.nan)
    return np.gradient(y, x)


def integral(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Cumulative trapezoidal integral, starting at 0."""
    if len(y) == 0:
        return y.copy()
    steps = (y[1:] + y[:-1]) / 2 * np.diff(x)
    return np.concatenate(([0.0], np.cumsum(steps)))


def lowpass(y: np.ndarray, x: np.ndarray, fc: float) -> np.ndarray:
    """First-order causal low-pass filter, cut-off ``fc`` (Hz, x in seconds).

    y[n] = y[n-1] + alpha (u[n] - y[n-1]) with alpha = dt / (RC + dt), RC = 1 / (2 pi fc), dt
    being the median sampling period. Computed block-wise in closed form (vectorised).
    """
    if fc <= 0:
        raise FormulaError("lowpass : la fréquence de coupure doit être > 0.")
    n = len(y)
    if n == 0:
        return y.copy()
    dt = float(np.median(np.diff(x))) if n > 1 else 1.0
    if not math.isfinite(dt) or dt <= 0:
        raise FormulaError("lowpass : vecteur temps non croissant.")
    rc = 1.0 / (2 * math.pi * fc)
    alpha = dt / (rc + dt)
    decay = 1.0 - alpha
    u = np.nan_to_num(y.astype(np.float64), nan=0.0)
    if decay <= 0.0:
        return u
    # Within a block of length B: y[j] = w^(j+1) y_prev + alpha sum_{k<=j} w^(j-k) u[k],
    # with w = decay.
    # B keeps w^-B below e^20 so the scaled cumulative sum stays accurate.
    block = int(max(1, min(4096, 20.0 / -math.log(decay))))
    out = np.empty(n)
    prev = u[0]
    powers = decay ** np.arange(1, block + 1)
    inv_powers = decay ** -np.arange(block)
    for start in range(0, n, block):
        chunk = u[start : start + block]
        m = len(chunk)
        acc = np.cumsum(chunk * inv_powers[:m]) * powers[:m] / decay
        values = powers[:m] * prev + alpha * acc
        out[start : start + m] = values
        prev = values[-1]
    return out


_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARY_OPS: dict[type, Callable[[Any], Any]] = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_COMPARE_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}
_ELEMENTWISE: dict[str, Callable[..., Any]] = {
    "abs": np.abs,
    "sqrt": np.sqrt,
    "exp": np.exp,
    "log": np.log,
    "log10": np.log10,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "minimum": np.minimum,
    "maximum": np.maximum,
    "clip": np.clip,
}
_WITH_X = {"derivative": 1, "integral": 1, "lowpass": 2}
"""Functions that need the X vector: name → number of arguments."""
FUNCTIONS = sorted([*_ELEMENTWISE, *_WITH_X])


def formula_variables(formula: str) -> list[str]:
    """Variable names used by ``formula`` in order of appearance (validates the syntax)."""
    tree = _parse(formula)
    names: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and node.id not in _CONSTANTS
            and node.id not in FUNCTIONS
            and node.id not in names
        ):
            names.append(node.id)
    # ast.walk is breadth-first: re-order by source position.
    positions: dict[str, tuple[int, int]] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in names:
            pos = (n.lineno, n.col_offset)
            positions[n.id] = min(pos, positions.get(n.id, pos))
    return sorted(names, key=lambda n: positions[n])


def _parse(formula: str) -> ast.Expression:
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Syntaxe invalide : {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise FormulaError("Fonction non autorisée.")
            if node.keywords:
                raise FormulaError("Arguments nommés non autorisés.")
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                raise FormulaError("Seules les constantes numériques sont autorisées.")
        elif not isinstance(
            node,
            (
                ast.Expression,
                ast.BinOp,
                ast.UnaryOp,
                ast.Compare,
                ast.Name,
                ast.Load,
                *_BIN_OPS,
                *_UNARY_OPS,
                *_COMPARE_OPS,
            ),
        ):
            raise FormulaError(f"Élément non autorisé : {type(node).__name__}")
    return tree


class _Evaluator:
    def __init__(self, env: Mapping[str, np.ndarray], x: np.ndarray) -> None:
        self.env = env
        self.x = x

    def eval(self, node: ast.AST) -> Value:
        if isinstance(node, ast.Expression):
            return self.eval(node.body)
        if isinstance(node, ast.Constant):
            assert isinstance(node.value, (int, float))  # checked by _parse
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in self.env:
                return self.env[node.id]
            if node.id in _CONSTANTS:
                return _CONSTANTS[node.id]
            raise FormulaError(f"Variable inconnue : {node.id}")
        if isinstance(node, ast.BinOp):
            return _BIN_OPS[type(node.op)](self.eval(node.left), self.eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return _UNARY_OPS[type(node.op)](self.eval(node.operand))
        if isinstance(node, ast.Compare):
            left = self.eval(node.left)
            result: Value = 1.0
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = self.eval(comparator)
                result = np.logical_and(result, _COMPARE_OPS[type(op)](left, right))
                left = right
            return np.asarray(result, dtype=np.float64)
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)
            name = node.func.id
            args = [self.eval(a) for a in node.args]
            if name in _WITH_X:
                if len(args) != _WITH_X[name]:
                    raise FormulaError(f"{name} attend {_WITH_X[name]} argument(s).")
                signal = self._as_array(args[0], name)
                if name == "lowpass":
                    if not isinstance(args[1], float):
                        raise FormulaError("lowpass : la fréquence doit être un nombre.")
                    return lowpass(signal, self.x, args[1])
                return (
                    derivative(signal, self.x) if name == "derivative" else integral(signal, self.x)
                )
            try:
                return _ELEMENTWISE[name](*args)
            except TypeError as exc:
                raise FormulaError(f"{name} : arguments invalides.") from exc
        raise FormulaError(f"Élément non autorisé : {type(node).__name__}")

    def _as_array(self, value: Value, name: str) -> np.ndarray:
        if isinstance(value, np.ndarray):
            return value
        return np.full(len(self.x), float(value))


def evaluate(config: DerivedSeriesConfig, resolve: Callable[[str], Series | None]) -> Series:
    """Compute a derived series. ``resolve`` maps a series id to a :class:`Series`."""
    tree = _parse(config.formula)
    used = formula_variables(config.formula)
    if not used:
        raise FormulaError("La formule doit utiliser au moins une série.")
    series: dict[str, Series] = {}
    for var in used:
        series_id = config.variables.get(var)
        if not series_id:
            raise FormulaError(f"Variable non affectée : {var}")
        s = resolve(series_id)
        if s is None:
            raise FormulaError(f"Série introuvable : {series_id}")
        series[var] = s
    ref = series[used[0]]
    x = ref.x
    env = {
        var: s.y if s.x is x or np.array_equal(s.x, x) else np.interp(x, s.x, s.y)
        for var, s in series.items()
    }
    with np.errstate(all="ignore"):
        result = _Evaluator(env, x).eval(tree)
    y = np.broadcast_to(np.asarray(result, dtype=np.float64), x.shape).copy()
    return Series(name=config.name, x=x, y=y, source=DERIVED_ALIAS, unit=config.unit)
