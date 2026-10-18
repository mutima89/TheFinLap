"""Safe arithmetic expression evaluator for user-defined metrics in the Modelling Workbench.

Supports numbers, + − × ÷ ^ (as ** or ^), parentheses, comparison, the functions
MIN, MAX, ABS, ROUND, IF, SAFEDIV and names that resolve to model values. No
attribute access, indexing, imports or arbitrary calls are possible (AST whitelist).
"""
from __future__ import annotations

import ast
import operator
from typing import Callable, Mapping

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod}
_CMP = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Eq: operator.eq,
        ast.NotEq: operator.ne}


class ExprError(ValueError):
    pass


def _safediv(a, b, default=None):
    return default if b == 0 else a / b


FUNCS: dict[str, Callable] = {
    "MIN": min, "MAX": max, "ABS": abs, "ROUND": lambda x, n=0: round(x, int(n)),
    "IF": lambda c, a, b: a if c else b, "SAFEDIV": _safediv,
}


def names_in(expr: str) -> set[str]:
    tree = _parse(expr)
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id.upper() not in FUNCS}


def _parse(expr: str) -> ast.Expression:
    if len(expr) > 500:
        raise ExprError("Expression too long (max 500 characters).")
    try:
        return ast.parse(expr.replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"Syntax error: {exc.msg}") from exc


def evaluate(expr: str, names: Mapping[str, float]) -> float:
    tree = _parse(expr)

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in names:
                raise ExprError(f"Unknown name '{n.id}'. Use a line-item key from the dependency viewer.")
            return names[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            l, r = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Div) and r == 0:
                raise ExprError("Division by zero – use SAFEDIV(a, b, default) if zero is possible.")
            return _BIN[type(n.op)](l, r)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in _CMP:
            return _CMP[type(n.ops[0])](ev(n.left), ev(n.comparators[0]))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id.upper() in FUNCS and not n.keywords:
            return FUNCS[n.func.id.upper()](*[ev(a) for a in n.args])
        raise ExprError(f"Unsupported element: {ast.dump(n)[:60]}")

    return ev(tree)
