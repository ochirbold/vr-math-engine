"""Bounded AST interpreter with execution-local context; never uses eval/exec."""
import ast
import math
import operator
from dataclasses import dataclass
from functools import reduce


class ModelError(ValueError):
    pass


COLUMN_FUNCTIONS = {"COLUMN", "COLUMN_SUM", "AGG_SUM", "AGG_MIN", "AGG_MAX"}
FUNCTIONS = COLUMN_FUNCTIONS | {"abs", "min", "max", "pow", "sqrt", "log", "exp", "positive_part", "POISSON_CAPPED_MEAN", "NB_CAPPED_MEAN", "SUM", "AVG", "COUNT", "DOT", "NORM", "vector"}


def parse(expression: str, constraint: bool = False) -> ast.AST:
    try:
        tree = ast.parse(expression, mode="eval").body
    except (SyntaxError, RecursionError) as exc:
        raise ModelError(f"Invalid expression: {expression}") from exc
    nodes = list(ast.walk(tree))
    parents = {child: parent for parent in nodes for child in ast.iter_child_nodes(parent)}
    if len(nodes) > 400:
        raise ModelError("Expression exceeds 400 AST nodes")
    allowed = (ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load, ast.List,
               ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)
    if constraint:
        if not isinstance(tree, ast.Compare) or len(tree.ops) != 1 or not isinstance(tree.ops[0], (ast.LtE, ast.GtE, ast.Eq)):
            raise ModelError("Constraint must be one <=, >= or == comparison")
    for node in nodes:
        if constraint and (node is tree or isinstance(node, (ast.LtE, ast.GtE, ast.Eq))):
            continue
        if not isinstance(node, allowed):
            raise ModelError(f"Unsupported expression syntax: {type(node).__name__}")
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float, str):
                raise ModelError("Only finite numbers and column-name strings are allowed")
            if isinstance(node.value, str):
                parent = parents.get(node)
                if not isinstance(parent, ast.Call) or not isinstance(parent.func, ast.Name) or parent.func.id not in COLUMN_FUNCTIONS:
                    raise ModelError("Strings are only allowed as column-function arguments")
            else:
                try:
                    if not math.isfinite(float(node.value)):
                        raise ModelError("Non-finite numeric literal")
                except OverflowError as exc:
                    raise ModelError("Numeric literal exceeds supported range") from exc
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
                raise ModelError("Only registered functions with positional arguments are allowed")
            if node.func.id in COLUMN_FUNCTIONS:
                if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                    raise ModelError("Column functions require a literal column name, e.g. COLUMN_SUM('QTY')")
    return tree


def references(tree):
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - FUNCTIONS
    columns = {n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and n.func.id in COLUMN_FUNCTIONS}
    return names, columns


def elementwise(a, b, fn):
    if isinstance(a, list) or isinstance(b, list):
        if not isinstance(a, list):
            a = [a] * len(b)
        if not isinstance(b, list):
            b = [b] * len(a)
        if len(a) != len(b):
            raise ModelError("Vector dimensions differ")
        return [fn(x, y) for x, y in zip(a, b)]
    return fn(a, b)


def power(a, b):
    if not isinstance(b, (int, float)) or abs(b) > 32:
        raise ModelError("Exponent must be a number between -32 and 32")
    return a ** b


def constant(value):
    # Symbolic values expose their constant only when there are no decision terms.
    if hasattr(value, "terms"):
        if value.terms:
            raise ModelError("Nonlinear function of a decision variable")
        return value.constant
    return value


def finite_scalar(value):
    value = constant(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ModelError("Expected a finite scalar result")
    return float(value)


@dataclass
class Context:
    values: dict
    rows: list[dict]
    positive_part_handler: object = None


def evaluate(tree, context: Context):
    def visit(node, depth=0):
        if depth > 40:
            raise ModelError("Expression nesting exceeds 40")
        call = lambda n: visit(n, depth + 1)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in context.values:
                raise ModelError(f"Unknown variable: {node.id}")
            return context.values[node.id]
        if isinstance(node, ast.List):
            return [call(x) for x in node.elts]
        if isinstance(node, ast.UnaryOp):
            value = call(node.operand)
            return elementwise(value, -1 if isinstance(node.op, ast.USub) else 1, operator.mul)
        if isinstance(node, ast.BinOp):
            operation = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                         ast.Div: operator.truediv, ast.Pow: power}[type(node.op)]
            return elementwise(call(node.left), call(node.right), operation)
        if isinstance(node, ast.Call):
            name = node.func.id
            args = [call(a) for a in node.args]
            if name in ("POISSON_CAPPED_MEAN", "NB_CAPPED_MEAN"):
                expected = 2 if name == "POISSON_CAPPED_MEAN" else 3
                if len(args) != expected:
                    raise ModelError(f"{name} requires {expected} scalar arguments")
                from .uncertainty import expected_capped_count
                values = [finite_scalar(a) for a in args]
                if name == "POISSON_CAPPED_MEAN":
                    return expected_capped_count("poisson", values[0], values[1])
                return expected_capped_count("negative_binomial", values[0], values[2], values[1])
            if name in COLUMN_FUNCTIONS:
                values = [row[args[0]] for row in context.rows]
                if name == "COLUMN":
                    return values
                return {"COLUMN_SUM": sum, "AGG_SUM": sum, "AGG_MIN": min, "AGG_MAX": max}[name](values)
            if name in ("SUM", "AVG", "COUNT", "NORM", "vector"):
                if len(args) != 1 or not isinstance(args[0], list) or not args[0]:
                    raise ModelError(f"{name} requires one nonempty vector")
                vector = args[0]
                if name == "vector":
                    return vector
                if name == "COUNT":
                    return len(vector)
                if name == "NORM":
                    return math.sqrt(sum(finite_scalar(x) ** 2 for x in vector))
                total = reduce(operator.add, vector, 0)
                return total / len(vector) if name == "AVG" else total
            if name == "DOT":
                if len(args) != 2 or not all(isinstance(x, list) for x in args):
                    raise ModelError("DOT requires two vectors")
                return sum(elementwise(args[0], args[1], operator.mul), 0)
            if name == "pow":
                if not 1 <= len(args) <= 2:
                    raise ModelError("pow takes one or two arguments")
                return power(args[0], args[1] if len(args) == 2 else 2)
            if name in ("abs", "sqrt", "log", "exp", "positive_part"):
                if len(args) != 1:
                    raise ModelError(f"{name} takes one argument")
                if name == "positive_part" and context.positive_part_handler is not None:
                    return context.positive_part_handler(args[0])
                value = finite_scalar(args[0])
                if name == "log" and value <= 0 or name == "sqrt" and value < 0:
                    raise ModelError(f"{name}: input outside function domain")
                return finite_scalar({"abs": abs, "sqrt": math.sqrt, "log": math.log, "exp": math.exp,
                                      "positive_part": lambda x: max(x, 0.)}[name](value))
            if name in ("min", "max"):
                values = args[0] if len(args) == 1 and isinstance(args[0], list) else args
                return (min if name == "min" else max)(finite_scalar(x) for x in values)
        raise ModelError("Unsupported expression")
    try:
        return visit(tree)
    except ModelError:
        raise
    except (ArithmeticError, TypeError, ValueError, KeyError) as exc:
        raise ModelError(str(exc)) from exc
