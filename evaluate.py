"""Synthetic policy coverage, not a real-world support accuracy benchmark."""
import itertools,json,time
from app.engine import decide

def evaluate():
    passed=0;cases=0;start=time.perf_counter()
    for plan,billing,status,enabled,incident,feature in itertools.product(['basic','pro','enterprise'],['active','past_due'],['active','suspended'],[0,1],[False,True],['reporting','exports']):
        a={'id':'a','plan':plan,'status':billing};m={'account_id':'a','status':status,'reporting':enabled}
        expected='escalate'
        if feature=='reporting' and not incident and billing=='active' and plan!='basic' and status=='active':
            expected='no_change' if enabled else 'restore_reporting'
        actual,_,_=decide(a,m,feature,incident)
        cases+=1;passed+=actual==expected
    return {'benchmark':'synthetic authorization matrix','cases':cases,'passed':passed,'elapsed_ms':round((time.perf_counter()-start)*1000,3),'limitations':'Policy consistency only; not real-world accuracy, retrieval quality, LLM quality or customer outcomes.'}

if __name__=='__main__':
    result=evaluate();print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed']==result['cases'] else 1)
