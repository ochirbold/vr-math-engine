"""Shape IR shared by statistical compilation and capability discovery.

Domains are runtime obligations, not a claim of symbolic interval proof.
LP decision linearity remains checked by the affine matrix builder.
"""
import ast
from dataclasses import dataclass
from .expressions import FUNCTIONS, COLUMN_FUNCTIONS, ModelError


@dataclass(frozen=True)
class Shape:
    kind: str = "scalar"
    length: int | None = None


SCALAR = Shape()
FUNCTION_CAPABILITIES = {
    name: {"domain": {"log": "x > 0", "sqrt": "x >= 0", "exp": "finite input and finite output",
                      "POISSON_CAPPED_MEAN": "(mean >= 0, 0 <= cap <= 1e12)",
                      "NB_CAPPED_MEAN": "(mean >= 0, dispersion > 0, 0 <= cap <= 1e12)"}.get(name, "finite numeric values"),
           "lp": "constant_only" if name in {"log", "exp", "sqrt", "abs", "min", "max", "NORM", "positive_part", "POISSON_CAPPED_MEAN", "NB_CAPPED_MEAN"} else "affine_rules"}
    for name in sorted(FUNCTIONS)
}


def infer_shape(tree, symbols, row_count=None):
    def combine(a, b):
        if a.kind == "scalar":
            return b
        if b.kind == "scalar":
            return a
        if a.length is not None and b.length is not None and a.length != b.length:
            raise ModelError("Vector dimensions differ")
        return Shape("vector", a.length if a.length is not None else b.length)

    def visit(node):
        if isinstance(node, ast.Constant):
            return SCALAR
        if isinstance(node, ast.Name):
            if node.id not in symbols:
                raise ModelError(f"Unknown variable: {node.id}")
            return symbols[node.id]
        if isinstance(node, ast.List):
            if not node.elts or any(visit(n).kind != "scalar" for n in node.elts):
                raise ModelError("Only nonempty, flat numeric vectors are supported")
            return Shape("vector", len(node.elts))
        if isinstance(node, ast.UnaryOp):
            return visit(node.operand)
        if isinstance(node, ast.BinOp):
            return combine(visit(node.left), visit(node.right))
        if isinstance(node, ast.Call):
            name = node.func.id
            if name in COLUMN_FUNCTIONS:
                return Shape("vector", row_count) if name == "COLUMN" else SCALAR
            args = [visit(n) for n in node.args]
            if name in {"SUM", "AVG", "COUNT", "NORM", "vector"}:
                if len(args) != 1 or args[0].kind != "vector":
                    raise ModelError(f"{name} requires one vector")
                return args[0] if name == "vector" else SCALAR
            if name == "DOT":
                if len(args) != 2 or any(a.kind != "vector" for a in args):
                    raise ModelError("DOT requires two vectors")
                combine(*args)
                return SCALAR
            if name in {"min", "max"}:
                if not args or (len(args) > 1 and any(a.kind != "scalar" for a in args)):
                    raise ModelError(f"{name} requires scalars or one vector")
                return SCALAR
            if name in {"POISSON_CAPPED_MEAN", "NB_CAPPED_MEAN"}:
                valid = len(args) == (2 if name == "POISSON_CAPPED_MEAN" else 3)
            elif name == "pow":
                valid = 1 <= len(args) <= 2
            else:
                valid = len(args) == 1
            if not valid or any(a.kind != "scalar" for a in args):
                raise ModelError(f"{name} requires scalar arguments")
            return SCALAR
        raise ModelError("Unsupported typed expression")

    return visit(tree)
