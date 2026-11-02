"""Finite, scalar quadrature over safe AST expressions; no domain-specific logic."""
from time import perf_counter
from scipy.integrate import quad
from .contracts import ExecutionResult
from .expressions import FUNCTIONS, Context, ModelError, parse, references, evaluate, finite_scalar
from .expression_types import SCALAR, infer_shape


def compile_integration(model):
    symbols = set(model.inputs + model.parameters)
    if (symbols | {model.variable}) & FUNCTIONS:
        raise ModelError('Integration identifiers cannot shadow registered functions')
    trees = []
    for expression, allowed in [(model.expression, symbols | {model.variable}),
                                 (model.lower, symbols), (model.upper, symbols)]:
        tree = parse(expression)
        names, columns = references(tree)
        if columns or names - allowed:
            raise ModelError('Integration expressions require declared local scalar symbols')
        if infer_shape(tree, {n: SCALAR for n in allowed}).kind != 'scalar':
            raise ModelError('Integration expressions must be scalar')
        trees.append(tree)
    return trees


class EvaluationLimit(Exception):
    pass


def integrate(request):
    start = perf_counter()
    model = request.model
    expression, lower, upper = compile_integration(model)
    if set(request.parameters) != set(model.parameters):
        raise ModelError('Parameters must exactly match integration declarations')
    if any(set(row) != set(model.inputs) for row in request.dataset.rows):
        raise ModelError('Dataset columns must exactly match integration inputs')
    outputs, rows_info = [], []
    evaluations = 0
    diagnostics = {'backend': 'scipy-quad/QUADPACK', 'scope': 'finite_one_dimensional',
                   'error_is_estimate': True, 'rows': rows_info}
    for row_id, row in zip(request.dataset.row_ids, request.dataset.rows):
        values = request.parameters | row
        def scalar(tree, env):
            return finite_scalar(evaluate(tree, Context(env, [])))
        a, b = scalar(lower, values), scalar(upper, values)
        def integrand(x):
            nonlocal evaluations
            if evaluations >= model.evaluation_limit:
                raise EvaluationLimit('Request-wide integrand evaluation limit reached')
            evaluations += 1
            return scalar(expression, values | {model.variable: x})
        before = evaluations
        try:
            if a == b:
                value, error, info, message = 0., 0., {'last': 0}, ''
            else:
                result = quad(integrand, min(a,b), max(a,b), epsabs=model.absolute_tolerance,
                              epsrel=model.relative_tolerance, limit=model.subdivision_limit,
                              full_output=1)
                value, error, info = result[:3]
                if b < a:
                    value = -value
                message = result[3] if len(result) > 3 else ''
                value, error = finite_scalar(value), finite_scalar(error)
                if error > max(model.absolute_tolerance, model.relative_tolerance*abs(value)) and not message:
                    message = 'Estimated error exceeds requested tolerance'
        except EvaluationLimit as exc:
            message, value, error, info = str(exc), None, None, {}
        rows_info.append({'row_id': row_id, 'converged': not bool(message),
                          'evaluations': evaluations-before, 'subintervals': info.get('last',0),
                          'message': message})
        if message:
            diagnostics.update(evaluations=evaluations, elapsed_seconds=perf_counter()-start)
            return ExecutionResult(model_id=model.model_id, model_version=model.version,
                                   status='failed', row_ids=request.dataset.row_ids, diagnostics=diagnostics)
        outputs.append({'integral': value, 'absolute_error_estimate': error})
    diagnostics.update(evaluations=evaluations, elapsed_seconds=perf_counter()-start)
    return ExecutionResult(model_id=model.model_id, model_version=model.version,
                           status='succeeded', row_ids=request.dataset.row_ids,
                           outputs=outputs, diagnostics=diagnostics)
