from functools import lru_cache
from itertools import product
import json
import math
from pathlib import Path
import pytest
from scipy.stats import nbinom, poisson
from math_engine.contracts import ExecutionRequest
from math_engine.engine import execute
from math_engine.expressions import ModelError
from math_engine.uncertainty import expected_capped_count
ROOT = Path(__file__).resolve().parents[1]
def example(name):
    return json.loads((ROOT/'examples'/f'{name}.json').read_text())
def run(raw):
    return execute(ExecutionRequest.model_validate(raw))
def direct(mean, cap, dispersion=None):
    dist = poisson(mean) if dispersion is None else nbinom(1/dispersion,1/(1+dispersion*mean))
    # Finite survival sum is independent of the truncated-moment implementation.
    n=math.floor(cap)
    return sum(dist.sf(k) for k in range(n))+(cap-n)*dist.sf(n)
@pytest.mark.parametrize('dispersion',[None,.4])
@pytest.mark.parametrize('mean,cap',[(0,3),(3,0),(4,.5),(4,3),(12,4),(1,100),(7,3.7)])
def test_capped_mean(mean,cap,dispersion):
    family='poisson' if dispersion is None else 'negative_binomial'
    assert expected_capped_count(family,mean,cap,dispersion)==pytest.approx(direct(mean,cap,dispersion),abs=1e-10)
@pytest.mark.parametrize('family,mean,cap,dispersion',[('poisson',-1,3,None),('poisson',1,-1,None),('poisson',1,float('inf'),None),('negative_binomial',1,3,0),('negative_binomial',1,3,-1),('unknown',1,3,None)])
def test_bad_parameters(family,mean,cap,dispersion):
    with pytest.raises(ModelError): expected_capped_count(family,mean,cap,dispersion)
def test_joint_prices_independent_enumeration():
    raw=example('finite_price_optimization'); p=raw['parameters']; row=raw['dataset']['rows'][0]
    candidates=[]
    for a,b in product([6,8,10],repeat=2):
        profit=0
        for sku,own,other in [('A',a,b),('B',b,a)]:
            mean=math.exp(p['intercept_'+sku]-p['elasticity_'+sku]*math.log(own)+p['cross_'+sku]*math.log(other)+p['competitor_coef']*math.log(9))
            profit+=(own-2)*direct(mean,row['stock_'+sku],p['dispersion_'+sku])
        candidates.append((profit,a,b))
    best=max(candidates); result=run(raw)
    assert result.objective==pytest.approx(best[0])
    assert result.solution=={'price_A':best[1],'price_B':best[2]}=={'price_A':8,'price_B':10}
    assert result.aggregates['expected_sales_A']<min(result.aggregates['mean_A'],5)
    row['stock_A']=row['stock_B']=0
    assert run(raw).objective==0

def test_markdown_independent_dynamic_program():
    raw=example('indexed_markdown'); rows=raw['dataset']['rows']
    demand={(r['t'],r['k'],r['s']):r['need'] for r in rows}
    price=[6,8,10]; scores=[]
    for ks in product(range(3),repeat=3):
        if any(ks[t]>ks[t-1] for t in [1,2]): continue
        @lru_cache(None)
        def future(t,stock,s):
            if t==3: return stock
            return max(price[ks[t]]*v-.2*(stock-v)+future(t+1,stock-v,s) for v in range(min(stock,demand[t,ks[t],s])+1))
        scores.append(max(price[ks[0]]*v-.2*(8-v)+sum(.5*future(1,8-v,s) for s in [0,1]) for v in range(min(8,demand[0,ks[0],0])+1)))
    result=run(raw)
    assert result.objective==pytest.approx(max(scores))==pytest.approx(64.3)
    assert result.solution['selling_price']==[10,10,10]
    assert min(result.solution['inventory'])>=0

def test_markdown_boundaries():
    raw=example('indexed_markdown')
    raw['parameters']['salvage']=12
    result=run(raw)
    assert result.objective==pytest.approx(91.2)
    assert sum(result.solution['sales'])==0
    raw['parameters']['initial']=0
    assert run(raw).objective==0
    raw=example('indexed_markdown'); raw['parameters']['price_floor']=9
    assert run(raw).solution['selling_price']==[10,10,10]
