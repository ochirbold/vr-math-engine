"""Independent exhaustive checks for small finite supplier/profit examples."""
from itertools import product
import json
from pathlib import Path
import pytest
from math_engine.contracts import ExecutionRequest
from math_engine.engine import execute
ROOT=Path(__file__).resolve().parents[1]
def raw(name): return json.loads((ROOT/'examples'/f'indexed_{name}.json').read_text())
def run(data): return execute(ExecutionRequest.model_validate(data))
def supplier_oracle(data):
 p=data['parameters']; options=[]
 for a,b in product(range(7),repeat=2):
  if a+b!=6 or any(q and not p['minimum']<=q<=p['capacity'] for q in [a,b]): continue
  gaps=[max(5-a-b,0),max(6-.5*a-b,0)]
  if sum(.5 for g in gaps if g>0)>p['epsilon']: continue
  options.append((a+3*b+p['setup']*((a>0)+(b>0))+p['penalty']*.5*sum(gaps),a,b))
 return min(options)
@pytest.mark.parametrize('epsilon',[0,.49,.5,1])
def test_supplier_against_enumeration(epsilon):
 data=raw('supplier'); data['parameters']['epsilon']=epsilon
 best=supplier_oracle(data); result=run(data)
 assert result.objective==pytest.approx(best[0])
 a,_,b,_=result.solution['order']
 assert a+b==6
 assert sum(.5 for demand,arrival in [(5,a+b),(6,.5*a+b)] if arrival<demand)<=epsilon
 assert result.solution['order']==[best[1],0,best[2],0]
 assert result.diagnostics['max_constraint_violation']<1e-7

def profit_oracle(data):
 p=data['parameters']; candidates=[]
 for a,b,allocation,k,y in product(range(5),range(5),range(9),range(2),range(2)):
  if any(q and not p['minimum']<=q<=p['capacity'] for q in [a,b]): continue
  if allocation>min(p['initial']+a+b,p['initial']+.5*a+b): continue
  if allocation>p['stock_cap']: continue
  demands=[[5,3][k],[7,5][k]]
  sales=[min(allocation,d) if y else 0 for d in demands]
  score=.5*sum([6,9][k]*v-p['holding']*(allocation-v) for v in sales)-a-3*b-p['setup']*((a>0)+(b>0))-p['allocation_cost']*allocation-p['shelf_cost']*y
  candidates.append((score,a,b,allocation,k,y))
 return max(candidates)
@pytest.mark.parametrize('initial,shelf_cost',[(1,1),(0,1),(1,100)])
def test_profit_against_joint_enumeration(initial,shelf_cost):
 data=raw('profit'); data['parameters'].update(initial=initial,shelf_cost=shelf_cost)
 best=profit_oracle(data); result=run(data)
 assert result.objective==pytest.approx(best[0])
 assert result.diagnostics['mip_gap']==0
 assert result.diagnostics['max_constraint_violation']<1e-7
 s=result.solution
 assert s['allocation'][0]==0
 assert s['order'][1]==s['order'][3]==0
 for w in range(2):
  for t in range(2):
   idx=2*t+w; before=s['before_sales'][idx]
   assert s['available'][idx]==int(before>=1)
   sold=sum(s['sales'][4*t+2*k+w] for k in range(2))
   assert s['stock'][idx]==pytest.approx(before-sold)
   if s['selected']==0: assert sold==0
 if shelf_cost==100:
  assert s['selected']==0
  assert sum(s['sales'])==0

def test_profit_baseline_and_shared_decisions():
 data=raw('profit'); result=run(data)
 for name in ['order','allocation','selected','facings','chosen']:
  assert 'w' not in data['model']['decisions'][name]['axes']
 assert result.objective==pytest.approx(22.3)
 assert result.solution['order']==[4,0,2,0]
 assert result.solution['allocation']==[0,5]
 assert result.solution['chosen']==[0,1]
 # Revenue 36 minus purchase 10, setup 2, holding .2, allocation .5, shelf 1.
 assert result.objective==pytest.approx(36-10-2-.2-.5-1)
