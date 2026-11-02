import json
import math
from pathlib import Path
import pytest
from pydantic import ValidationError
from math_engine.contracts import ExecutionRequest
from math_engine.engine import execute
from math_engine.compiler import validate_model
from math_engine.expressions import ModelError

def request(expression='x**2',lower='0',upper='1',**options):
 return ExecutionRequest.model_validate(dict(model=dict(model_id='integral-test',version='1',kind='numerical_integration',expression=expression,lower=lower,upper=upper,**options),dataset=dict(row_ids=['a'],rows=[{}])))
@pytest.mark.parametrize('expression,lower,upper,expected',[
 ('x**2','0','1',1/3),('exp(-x)','0','2',1-math.exp(-2)),
 ('1/sqrt(x)','0','1',2),('x','2','-1',-1.5),('x','2','2',0),
 ('abs(x)','-1','1',1),('log(x)','1','2',2*math.log(2)-1)])
def test_analytic(expression,lower,upper,expected):
 r=execute(request(expression,lower,upper))
 assert r.status=='succeeded'
 assert r.outputs[0]['integral']==pytest.approx(expected,abs=1e-8)
 assert r.outputs[0]['absolute_error_estimate']>=0
 assert r.diagnostics['rows'][0]['converged']
def test_rows_and_parameters():
 raw=json.loads(Path('examples/integration.json').read_text()); r=execute(ExecutionRequest.model_validate(raw))
 assert [o['integral'] for o in r.outputs]==[8,-8]
 assert r.row_ids==['forward','reverse']
 raw['model']['evaluation_limit']=25
 r=execute(ExecutionRequest.model_validate(raw))
 assert r.status=='failed' and not r.outputs
 assert r.diagnostics['evaluations']==25
@pytest.mark.parametrize('expression,lower',[('unknown+x','0'),('vector(1,2)','0'),("COLUMN_SUM('x')",'0'),('x','x'),("__import__('os')",'0')])
def test_invalid_ast(expression,lower):
 with pytest.raises(ModelError): validate_model(request(expression,lower).model)
def test_domain_error():
 with pytest.raises(ModelError): execute(request('log(x)','-2','-1'))
def test_nonconvergence():
 r=execute(request('abs(x-.123456789)','0','1',subdivision_limit=1))
 assert r.status=='failed' and not r.outputs
 assert not r.diagnostics['rows'][0]['converged']
@pytest.mark.parametrize('options',[dict(absolute_tolerance=0),dict(relative_tolerance=float('nan')),dict(subdivision_limit=0),dict(evaluation_limit=0),dict(variable='exp')])
def test_invalid_options(options):
 with pytest.raises((ValidationError,ModelError)):
  validate_model(request(**options).model)
def test_mismatched_inputs():
 r=request(); r.parameters={'extra':1}
 with pytest.raises(ModelError): execute(r)
