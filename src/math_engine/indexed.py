"""Finite indexed deterministic-equivalent compiler; no application rules.

Subscripts are resolved at compile time. No Python execution, arbitrary lookups,
implicit boundary values, or inferred decision information is permitted.
"""
import ast
from itertools import product
from types import SimpleNamespace

from .compiler import Program
from .contracts import Decision, ExecutionResult
from .expressions import COLUMN_FUNCTIONS, FUNCTIONS, Context, ModelError, evaluate, finite_scalar, parse, references
from .expression_types import SCALAR, infer_shape
from .linear import ScipySolver, build_matrix


def coordinates(model, axes):
    return product(*(model.axes[a] for a in axes))


def indexed_parse(text, constraint=False):
    try:
        tree = ast.parse(text, mode="eval").body
    except (SyntaxError, RecursionError) as exc:
        raise ModelError("Invalid indexed expression") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 400:
        raise ModelError("Indexed expression exceeds 400 AST nodes")
    allowed = (ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load, ast.List, ast.Tuple,
               ast.Call, ast.Subscript, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)
    if constraint:
        if not isinstance(tree, ast.Compare) or len(tree.ops) != 1 or not isinstance(tree.ops[0], (ast.LtE, ast.GtE, ast.Eq)):
            raise ModelError("Indexed constraint requires one <=, >= or ==")
    for node in nodes:
        if constraint and (node is tree or isinstance(node, (ast.LtE, ast.GtE, ast.Eq))):
            continue
        if not isinstance(node, allowed):
            raise ModelError(f"Unsupported indexed syntax: {type(node).__name__}")
        if isinstance(node, ast.Constant) and type(node.value) not in (int, float):
            raise ModelError("Indexed expressions accept only numeric constants")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in (FUNCTIONS-COLUMN_FUNCTIONS) | {"SUM_OVER"} or node.keywords):
            raise ModelError("Only registered numeric functions are allowed")
        if isinstance(node, ast.Subscript) and not isinstance(node.value, ast.Name):
            raise ModelError("Only named tensors can be indexed")
    return tree


def validate_indexed(model):
    names = set(model.axes) | set(model.tables) | set(model.decisions) | set(model.parameters)
    if names & (FUNCTIONS | {"SUM_OVER"}):
        raise ModelError("Indexed symbols cannot shadow registered functions")
    for term, constraint in [(t, False) for t in model.objective.terms] + [(t, True) for t in model.constraints]:
        tree = indexed_parse(term.expression, constraint)
        if {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - names - FUNCTIONS - {"SUM_OVER"}:
            raise ModelError("Unknown indexed symbol")
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript):
                if node.value.id not in model.tables and node.value.id not in model.decisions:
                    raise ModelError("Subscript requires a declared table or decision")
        def check_scope(node, bound):
            if isinstance(node, ast.Call) and node.func.id == "SUM_OVER":
                if len(node.args) != 2 or not isinstance(node.args[0], ast.Name) or node.args[0].id not in model.axes:
                    raise ModelError("SUM_OVER requires an axis name and a numeric expression")
                axis = node.args[0].id
                if axis in bound:
                    raise ModelError("SUM_OVER cannot shadow an already bound axis")
                check_scope(node.args[1], bound | {axis})
                return
            if isinstance(node, ast.Name) and node.id in model.axes and node.id not in bound:
                raise ModelError(f"Unbound axis {node.id}")
            for child in ast.iter_child_nodes(node):
                check_scope(child, bound)
        check_scope(tree, set(term.over))
    # Validate explicit, complete information partitions independent of data.
    for name, spec in model.decisions.items():
        seen_boundaries = set()
        for boundary in spec.boundary:
            index = tuple(boundary.index)
            if len(index) != len(spec.axes) or index in seen_boundaries:
                raise ModelError(f"{name}: duplicate or wrong-rank boundary")
            if all(v in model.axes[a] for a, v in zip(spec.axes, index)):
                raise ModelError(f"{name}: boundary cannot override an actual decision")
            used, columns = references(parse(boundary.expression))
            if used - set(model.parameters) or columns:
                raise ModelError("Boundary values may reference only fixed parameters")
            seen_boundaries.add(index)
        if not isinstance(spec.information, list):
            continue
        remaining = [a for a in spec.axes if a != model.scenario_axis]
        expected = set(coordinates(model, remaining))
        covered = set()
        for info in spec.information:
            if set(info.at) != set(remaining):
                raise ModelError("Information partition must bind every non-scenario decision axis")
            coordinate = tuple(info.at[a] for a in remaining)
            if coordinate not in expected or coordinate in covered:
                raise ModelError("Duplicate or invalid information coordinate")
            flat = [s for group in info.groups for s in group]
            if any(not group for group in info.groups) or len(flat) != len(set(flat)) or set(flat) != set(model.axes[model.scenario_axis]):
                raise ModelError("Information groups must partition all scenarios exactly once")
            covered.add(coordinate)
        if covered != expected:
            raise ModelError("Information partitions must cover every decision coordinate")


def compile_indexed(request):
    model = request.model
    validate_indexed(model)
    if set(request.parameters) != set(model.parameters):
        raise ModelError("Fixed parameters must exactly match declarations")
    if any(set(row) != set(model.inputs) for row in request.dataset.rows):
        raise ModelError("Dataset columns must exactly match indexed model inputs")
    tables = {}
    for name, spec in model.tables.items():
        values = {}
        for row in request.dataset.rows:
            key = tuple(row[a] for a in spec.axes)
            if any(v != int(v) or int(v) not in model.axes[a] for a, v in zip(spec.axes, key)):
                raise ModelError(f"{name}: data axis value is outside its declared domain")
            key = tuple(int(v) for v in key)
            value = row[spec.column]
            if key in values and values[key] != value:
                raise ModelError(f"{name}: conflicting data for coordinate {key}")
            values[key] = value
        if set(values) != set(coordinates(model, spec.axes)):
            raise ModelError(f"{name}: missing tensor data")
        tables[name] = values
    if model.scenario_axis:
        weights = list(tables[model.probability_table].values())
        if any(w <= 0 for w in weights) or abs(sum(weights)-1) > 1e-9:
            raise ModelError("Scenario probabilities must be positive and sum to one")
    decisions, symbols, boundaries, layout = {}, {}, {}, {}
    for name, spec in model.decisions.items():
        symbols[name] = {}
        coords = list(coordinates(model, spec.axes))
        for index in coords:
            symbol = f"__v{len(decisions)}"
            symbols[name][index] = symbol
            decisions[symbol] = Decision(domain=spec.domain, lower=spec.lower, upper=spec.upper)
        boundaries[name] = {tuple(b.index): finite_scalar(evaluate(parse(b.expression), Context(request.parameters, []))) for b in spec.boundary}
        layout[name] = {"axes": spec.axes, "indices": [list(c) for c in coords], "symbols": list(symbols[name].values()),
                        "information": "shared_across_scenarios" if model.scenario_axis and model.scenario_axis not in spec.axes else
                                       "explicit_partitions" if isinstance(spec.information, list) else spec.information}

    expansion_budget = [100000]

    class Resolver(ast.NodeTransformer):
        def __init__(self, bindings, indices_only=False):
            self.bindings = bindings
            self.indices_only = indices_only

        def visit_Name(self, node):
            if node.id in self.bindings:
                return ast.Constant(self.bindings[node.id])
            if node.id in symbols:
                if self.indices_only or () not in symbols[node.id]:
                    raise ModelError("Indexed decisions require explicit subscripts and cannot determine indices")
                return ast.Name(symbols[node.id][()], ast.Load())
            if node.id in tables:
                if () not in tables[node.id]:
                    raise ModelError("Indexed tables require explicit subscripts")
                return ast.Constant(tables[node.id][()])
            return node

        def visit_Call(self, node):
            if node.func.id != "SUM_OVER":
                return self.generic_visit(node)
            if len(node.args) != 2 or not isinstance(node.args[0], ast.Name) or node.args[0].id not in model.axes:
                raise ModelError("SUM_OVER requires an axis name and a numeric expression")
            axis = node.args[0].id
            if axis in self.bindings:
                raise ModelError("SUM_OVER cannot shadow an already bound axis")
            import copy
            children = []
            for label in model.axes[axis]:
                expansion_budget[0] -= 1
                if expansion_budget[0] < 0:
                    raise ModelError("Indexed summation expansion exceeds 100000 terms")
                children.append(Resolver(self.bindings | {axis: label}, self.indices_only).visit(copy.deepcopy(node.args[1])))
            return ast.Call(ast.Name("SUM", ast.Load()), [ast.List(children, ast.Load())], [])

        def visit_Subscript(self, node):
            name = node.value.id
            indices = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            key = []
            for index in indices:
                resolved = Resolver(self.bindings, True).visit(index)
                tree = parse(ast.unparse(ast.fix_missing_locations(resolved)))
                used, cols = references(tree)
                if cols or used - set(request.parameters):
                    raise ModelError("Indices must depend only on bound axes, data, and fixed parameters")
                value = finite_scalar(evaluate(tree, Context(request.parameters, [])))
                if value != int(value):
                    raise ModelError("Tensor indices must be integers")
                key.append(int(value))
            key = tuple(key)
            if name in tables:
                if key not in tables[name]:
                    raise ModelError(f"Missing table entry {name}{key}")
                return ast.Constant(tables[name][key])
            if self.indices_only:
                raise ModelError("Decision variables cannot determine indices")
            if key in symbols[name]:
                return ast.Name(symbols[name][key], ast.Load())
            if key in boundaries[name]:
                return ast.Constant(boundaries[name][key])
            raise ModelError(f"Missing decision/boundary {name}{key}")

    def expand(term, constraint=False):
        for coordinate in coordinates(model, term.over):
            bindings = dict(zip(term.over, coordinate))
            original = indexed_parse(term.expression, constraint)
            translated = Resolver(bindings).visit(original)
            tree = parse(ast.unparse(ast.fix_missing_locations(translated)), constraint=constraint)
            used, cols = references(tree)
            if cols or used - set(request.parameters) - set(decisions):
                raise ModelError("Unresolved indexed symbol")
            expressions = [tree.left, tree.comparators[0]] if constraint else [tree]
            for expr in expressions:
                if infer_shape(expr, {n: SCALAR for n in used}).kind != "scalar":
                    raise ModelError("Indexed terms must be scalar")
            yield tree, f"{bindings}: {term.expression}"

    objective_terms = [tree for term in model.objective.terms for tree, _ in expand(term)]
    objective = ast.Call(ast.Name("SUM", ast.Load()), [ast.List(objective_terms, ast.Load())], [])
    constraints = [pair for term in model.constraints for pair in expand(term, True)]
    information_equalities = 0
    for name, spec in model.decisions.items():
        if not isinstance(spec.information, list):
            continue
        for info in spec.information:
            for group in info.groups:
                def symbol(s):
                    point = info.at | {model.scenario_axis: s}
                    return symbols[name][tuple(point[a] for a in spec.axes)]
                for s in group[1:]:
                    constraints.append((parse(f"{symbol(group[0])} == {symbol(s)}", constraint=True),
                                        f"information:{name}:{info.at}:{group[0]}={s}"))
                    information_equalities += 1
    if len(constraints) > 5000:
        raise ModelError("Expanded constraints exceed 5000")
    flat = SimpleNamespace(kind="mixed_integer_program", decisions=decisions, objective=model.objective,
                           constraints=[source for _, source in constraints])
    program = Program({}, objective, [tree for tree, _ in constraints])
    matrix = build_matrix(flat, program, [], request.parameters)
    return matrix, layout, information_equalities


def execute_indexed(request, solver=None):
    matrix, layout, equalities = compile_indexed(request)
    solved = (solver or ScipySolver()).solve(matrix, request.solver)
    diagnostics = solved["diagnostics"] | {"indexed_layout": layout, "information_equalities": equalities,
                                           "model_scope": "explicit_finite_deterministic_equivalent"}
    result = dict(model_id=request.model.model_id, model_version=request.model.version,
                  row_ids=request.dataset.row_ids, status=solved["status"], diagnostics=diagnostics)
    if solved["status"] != "succeeded":
        return ExecutionResult(**result)
    solution = {}
    for name, info in layout.items():
        values = [solved["x"][matrix.groups[s][0]] for s in info["symbols"]]
        solution[name] = values if info["axes"] else values[0]
    return ExecutionResult(**result, solution=solution, objective=solved["objective"],
                           outputs=[{} for _ in request.dataset.rows])
