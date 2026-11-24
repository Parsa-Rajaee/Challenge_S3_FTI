import numpy as np
import pandas as pd
import pytest
from capstone.core import FEATURES, audit_features, select_top, evaluate, rank_orders, temporal_split
from capstone.runner import feature_drift,validate_new_orders,models

def test_approved(): audit_features()
@pytest.mark.parametrize('bad',['review_score','order_delivered_customer_date','order_status','future_column','review_creation_date'])
def test_leakage_rejected(bad):
    with pytest.raises(ValueError):audit_features((*FEATURES,bad))
@pytest.mark.parametrize('capacity,count',[(.05,5),(.10,10),(.20,20)])
def test_quota(capacity,count):assert select_top(np.arange(100),capacity).sum()==count
def test_hard_capacity():assert select_top(np.arange(21),.05).sum()==1
def test_tie():assert select_top([1,1,1],.5).tolist()==[True,False,False]


def test_ranked_ties_keep_flags_at_top_regardless_of_input_order():
    orders = pd.DataFrame({
        "order_id": ["a", "c", "b"],
        "approved_at": pd.to_datetime(["2018-01-02", "2018-01-01", "2018-01-01"]),
    })
    for order in (orders, orders.iloc[::-1]):
        ranked = rank_orders(order, [0.5] * len(order), capacity=0.5)
        assert ranked.order_id.tolist() == ["b", "c", "a"]
        assert ranked.follow_up.tolist() == [True, False, False]


def test_unreviewed_batch_keeps_capacity_counts():
    result = evaluate([None] * 10, np.arange(10))
    assert result["total_flagged"] == 1
    assert result["selected"] == result["n"] == result["positives"] == 0
    assert result["recall"] is result["precision"] is None

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


def test_precomputed_csv_preserves_zip_region(tmp_path):
    values = dict.fromkeys(FEATURES, 1)
    values.update(customer_zip_region="01", order_id="0023", approved_at="2018-01-01")
    path = tmp_path / "orders.csv"
    pd.DataFrame([values]).to_csv(path, index=False)
    row = validate_new_orders(path).iloc[0]
    assert row.customer_zip_region == "01"
    assert row.order_id == "0023"

def test_drift():
    frame=pd.DataFrame({c:(['SP','RJ'] if c in ('customer_state','customer_zip_region') else [1,2]) for c in FEATURES})
    assert feature_drift(frame,frame)['approval_hour']['standardized_mean_shift']==0
def test_synthetic_model_path():
    df=pd.DataFrame([{c:('SP' if i%2 else 'RJ') if c in ('customer_state','customer_zip_region') else i%11 for c in FEATURES} for i in range(64)])
    labels=np.array([int(i%4==0) for i in range(64)])
    for model in models().values():
        model.fit(df,labels);pred=model.predict_proba(df)[:,1]
        assert np.isfinite(pred).all() and select_top(pred).sum()==6
