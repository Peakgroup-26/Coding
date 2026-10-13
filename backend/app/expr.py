"""Safe evaluation of rule quantity formulas.

Formulas are plain arithmetic, e.g. `n`, `2 * n`, `ceil(m / 1.2)`, `max(1, m * 0.05)`.

Variables available, by trigger:
    per_fixture  n = number of matching fixtures (1 per source)
    per_metre    m = metres of run (plan + vertical, before waste)
    per_bend     n = changes of direction in the angle band
    per_branch   n = branch connections
    per_io       n = IO locations required
    per_job      m = total pipe metres of matching runs, fixtures = total fixtures, n = 1
Every formula can also use: dn (pipe size, 0 for per_job and fixtures without a run).
"""
import ast
import math
import operator

FUNCTIONS = {"ceil": math.ceil, "floor": math.floor, "round": round, "min": min, "max": max, "abs": abs}
VARIABLES = ("n", "m", "dn", "fixtures")

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class FormulaError(ValueError):
    pass


def _eval(node, env):
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise FormulaError(f"Unknown name '{node.id}'. Use: {', '.join(VARIABLES)}")
        return env[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise FormulaError("Exponent too large")
        try:
            return _BIN[type(node.op)](left, right)
        except ZeroDivisionError:
            raise FormulaError("Division by zero")
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, env))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
        return FUNCTIONS[node.func.id](*[_eval(a, env) for a in node.args])
    raise FormulaError("Only numbers, n, m, dn, fixtures, + - * / and ceil/floor/round/min/max/abs are allowed")


def evaluate(formula: str, **variables) -> float:
    if len(formula or "") > 500:
        raise FormulaError("Formula is too long")
    try:
        tree = ast.parse((formula or "").strip(), mode="eval")
    except SyntaxError:
        raise FormulaError(f"Can't read formula '{formula}'")
    env = {k: 0 for k in VARIABLES} | {k: v for k, v in variables.items() if v is not None}
    value = _eval(tree, env)
    return float(value)


def validate(formula: str) -> None:
    """Raise FormulaError if the formula can't be evaluated with sample values."""
    evaluate(formula, n=1, m=1, dn=100, fixtures=1)
