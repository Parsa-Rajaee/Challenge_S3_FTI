"""Audited feature contract, temporal holdout, and operational metrics."""
import math
import numpy as np
from sklearn.metrics import confusion_matrix,precision_score,recall_score,f1_score,roc_auc_score

FEATURES = (
    "approval_weekday",
    "approval_month",
    "approval_hour",
    "approval_lag_hours",
    "purchase_hour",
    "purchase_weekday",
    "is_weekend",
    "is_public_holiday",
    "customer_state",
    "customer_zip_region",
    "prior_day_shipments",
    "prior_day_deliveries",
    "prior_day_replies",
    "prior_day_negatives",
)
CATEGORICAL=('customer_state','customer_zip_region')
BANNED={'review_score','review_creation_date','order_status','order_delivered_customer_date','order_delivered_carrier_date','review_answer_timestamp','review_comment_message'}
def audit_features(columns=FEATURES):
    unknown=set(columns)-set(FEATURES)
    if unknown or set(columns)&BANNED:
        raise ValueError(f'Unapproved or leaky features: {sorted(unknown | (set(columns)&BANNED))}')
def select_top(scores,capacity=.10):
    if not 0<capacity<=1: raise ValueError('capacity must be in (0,1]')
    values=np.asarray(scores,dtype=float)
    if not np.isfinite(values).all(): raise ValueError('scores must be finite')
    chosen=np.zeros(len(values),dtype=bool)
    quota = math.floor(len(values) * capacity)
    ranking = np.argsort(-values, kind='stable')
    chosen[ranking[:quota]] = True
    return chosen
def evaluate(y,scores,capacity=.10):
    # Rank every approved order, including those whose outcome is unknown.
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(y, dtype=float)
    if len(labels) != len(scores):
        raise ValueError('Invalid binary evaluation input')
    selected = select_top(scores, capacity)
    known = np.isfinite(labels)
    if not np.isin(labels[known], [0, 1]).all():
        raise ValueError('Invalid binary evaluation input')
    y = labels[known]
    scores = scores[known]
    pred = selected[known]
    y=np.asarray(y,dtype=int);scores=np.asarray(scores,dtype=float)
    if not len(y) or len(y)!=len(scores) or not set(np.unique(y)).issubset({0,1}): raise ValueError('Invalid binary evaluation input')
    return {'eligible_orders':len(labels),'total_flagged':int(selected.sum()),'n':len(y),'positives':int(y.sum()),'selected':int(pred.sum()),'precision':float(precision_score(y,pred,zero_division=0)),'recall':float(recall_score(y,pred,zero_division=0)),'f1':float(f1_score(y,pred,zero_division=0)),'roc_auc':float(roc_auc_score(y,scores)) if len(set(y))==2 else None,'confusion_matrix_tn_fp_fn_tp':confusion_matrix(y,pred,labels=[0,1]).ravel().tolist()}
def temporal_split(frame,fraction=.8):
    periods=frame.approved_at.dt.to_period('M');months=sorted(periods.dropna().unique())
    if len(months)<3: raise ValueError('At least three approval months required')
    cutoff=months[max(1,min(len(months)-1,math.floor(len(months)*fraction)))]
    train=frame.loc[periods<cutoff].copy();test=frame.loc[periods>=cutoff].copy()
    if train.empty or test.empty: raise ValueError('Empty temporal split')
    return train,test,str(cutoff)
