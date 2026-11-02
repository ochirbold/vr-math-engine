from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from math_engine.contracts import ExecutionRequest, ModelSpec, Dataset
from math_engine.compiler import compile_model
from math_engine.engine import execute
from math_engine.expressions import ModelError, parse
from math_engine.linear import ScipySolver

ROOT = Path(__file__).resolve().parents[1]


def sample(name):
    return json.loads((ROOT / 'examples' / (name + '.json')).read_text())


def test_calculation_dependencies_and_aggregate_of_computed_column():
    request = ExecutionRequest.model_validate(sample('calculation'))
    original = request.model_dump()
    result = execute(request)
    assert request.model_dump() == original
    assert result.status == 'succeeded'
    assert result.aggregates == {'TOTAL_QTY': 5, 'HIGH_PRICE': 120, 'GRAND_TOTAL': 435}
    assert result.outputs == [
        {'TOTAL': 240, 'NET': 225, 'PRICE_GAP': 0, 'SCENARIO_QTY': 5},
        {'TOTAL': 240, 'NET': 210, 'PRICE_GAP': 40, 'SCENARIO_QTY': 5}]


def test_execution_contexts_are_isolated():
    def run(quantity):
        raw = sample('calculation')
        raw['dataset']['rows'][0]['QTY'] = quantity
        return execute(ExecutionRequest.model_validate(raw)).aggregates['TOTAL_QTY']
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(run, range(20))) == [i + 3 for i in range(20)]


def test_linear_vector_maximization_with_objective_constant():
    result = execute(ExecutionRequest.model_validate(sample('allocation')))
    assert result.status == 'succeeded'
    assert result.solution['allocation'] == pytest.approx([4, 2])
    assert result.objective == pytest.approx(59)
    assert result.outputs == [{'ALLOCATED': 4}, {'ALLOCATED': 2}]
    assert result.diagnostics['max_constraint_violation'] <= 1e-7


def lp(constraints, sense='minimize', objective='3 * amount + 2'):
    return ExecutionRequest.model_validate({'model': {
        'model_id': 'scalar', 'version': '1', 'kind': 'linear_program',
        'decisions': {'amount': {'lower': 0}},
        'objective': {'sense': sense, 'expression': objective}, 'constraints': constraints},
        'dataset': {'row_ids': ['1'], 'rows': [{}]}})


def test_equality_and_minimize():
    result = execute(lp(['amount == 4']))
    assert result.objective == pytest.approx(14)
    assert result.solution == {'amount': 4}


@pytest.mark.parametrize('constraints,sense,status', [
    (['amount <= 1', 'amount >= 2'], 'minimize', 'infeasible'),
    ([], 'maximize', 'unbounded')])
def test_solver_failure_states(constraints, sense, status):
    result = execute(lp(constraints, sense))
    assert result.status == status
    assert result.outputs == []


@pytest.mark.parametrize('expression', ['amount * amount', 'amount ** 2', 'sqrt(amount)', '1 / amount'])
def test_reject_nonlinearity(expression):
    with pytest.raises(ModelError):
        execute(lp(['amount <= 10'], objective=expression))


@pytest.mark.parametrize('expression', ["__import__('os')", 'a.__class__', '[x for x in [1]]',
                                       'max(x=2)', "'x' * 1000000000", 'True', '1e999', 'a[0]'])
def test_reject_unsafe_or_unsupported_ast(expression):
    with pytest.raises(ModelError):
        parse(expression)


def test_cycles_and_stage_errors():
    for formulas in [
        [{'target': 'a', 'expression': 'b'}, {'target': 'b', 'expression': 'a'}],
        [{'target': 'a', 'expression': "COLUMN_SUM('x')"}],
        [{'target': 'a', 'expression': 'x', 'stage': 'aggregate'}],
    ]:
        with pytest.raises(ModelError):
            compile_model(ModelSpec(model_id='bad', version='1', inputs=['x'], formulas=formulas))


def test_dimension_and_missing_input_validation():
    with pytest.raises(ValidationError):
        Dataset(row_ids=['1', '1'], rows=[{'x': 1}, {'x': 2}])
    raw = sample('allocation')
    raw['parameters'] = {}
    with pytest.raises(ModelError):
        execute(ExecutionRequest.model_validate(raw))
    raw = sample('allocation')
    raw['model']['objective']['expression'] = 'DOT([1, 2, 3], allocation)'
    with pytest.raises(ModelError):
        execute(ExecutionRequest.model_validate(raw))


def test_solver_adapter_is_replaceable():
    class RecordingSolver:
        def solve(self, matrix, config):
            assert matrix.variables == ['amount']
            return {'status': 'failed', 'diagnostics': {'adapter': 'test'}}
    assert execute(lp([]), RecordingSolver()).diagnostics == {'adapter': 'test'}
