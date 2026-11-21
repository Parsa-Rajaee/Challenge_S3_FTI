import numpy as np
import pandas as pd
import pytest
from capstone.core import FEATURES,audit_features,select_top,evaluate,temporal_split
from capstone.runner import feature_drift,validate_new_orders,models

def test_approved(): audit_features()
@pytest.mark.parametrize('bad',['review_score','order_delivered_customer_date','order_status','future_column','review_creation_date'])
def test_leakage_rejected(bad):
    with pytest.raises(ValueError):audit_features((*FEATURES,bad))
@pytest.mark.parametrize('capacity,count',[(.05,5),(.10,10),(.20,20)])
def test_quota(capacity,count):assert select_top(np.arange(100),capacity).sum()==count
def test_hard_capacity():assert select_top(np.arange(21),.05).sum()==1
def test_tie():assert select_top([1,1,1],.5).tolist()==[True,False,False]
@pytest.mark.parametrize('capacity',[0,1.1,-.2])
def test_invalid_capacity(capacity):
    with pytest.raises(ValueError):select_top([.2],capacity)
def test_nan():
    with pytest.raises(ValueError):select_top([float('nan')])
def test_perfect():assert evaluate([1,0,0,0,0,0,0,0,0,0],[1,0,0,0,0,0,0,0,0,0])['recall']==1
def test_empty():
    with pytest.raises(ValueError):evaluate([],[])
def test_temporal():
    df=pd.DataFrame({'approved_at':pd.to_datetime(['2017-01-01','2017-02-01','2017-03-01','2017-04-01'])})
    a,b,_=temporal_split(df);assert a.approved_at.max()<b.approved_at.min()
def test_insufficient_months():
    with pytest.raises(ValueError):temporal_split(pd.DataFrame({'approved_at':pd.to_datetime(['2017-01-01'])}))
def test_bad_schema(tmp_path):
    file=tmp_path/'orders.csv';file.write_text('order_id,review_score\na,1\n')
    with pytest.raises(ValueError,match='schema mismatch'):validate_new_orders(file)
def test_duplicate(tmp_path):
    frame=pd.DataFrame([{**dict.fromkeys(FEATURES,1),'order_id':'a','approved_at':'2018-01-01'}]*2)
    file=tmp_path/'orders.csv';frame.to_csv(file,index=False)
    with pytest.raises(ValueError,match='unique'):validate_new_orders(file)
def test_numeric(tmp_path):
    frame=pd.DataFrame([{**dict.fromkeys(FEATURES,1),'order_id':'a','approved_at':'2018-01-01','approval_hour':'garbage'}])
    file=tmp_path/'orders.csv';frame.to_csv(file,index=False)
    with pytest.raises(ValueError):validate_new_orders(file)
def test_drift():
    frame=pd.DataFrame({c:(['SP','RJ'] if c in ('customer_state','customer_zip_region') else [1,2]) for c in FEATURES})
    assert feature_drift(frame,frame)['approval_hour']['standardized_mean_shift']==0
def test_synthetic_model_path():
    df=pd.DataFrame([{c:('SP' if i%2 else 'RJ') if c in ('customer_state','customer_zip_region') else i%11 for c in FEATURES} for i in range(64)])
    labels=np.array([int(i%4==0) for i in range(64)])
    for model in models().values():
        model.fit(df,labels);pred=model.predict_proba(df)[:,1]
        assert np.isfinite(pred).all() and select_top(pred).sum()==6
