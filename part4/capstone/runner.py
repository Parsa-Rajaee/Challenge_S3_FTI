"""Build, evaluate, and score Olist orders. Outputs are evidence, not invented metrics."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd
from sqlalchemy import create_engine,text
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from .core import FEATURES,CATEGORICAL,audit_features,evaluate,select_top,temporal_split
from .external import acquire_holidays
from .raw_orders import raw_features, feature_query, ensure_calendar
from .reporting import write_reports
ROOT=Path(__file__).resolve().parents[1]
STAGE2=ROOT.parent/'part2'/'stage-2-database-performance'
def preprocess(columns=FEATURES):
    numbers = [column for column in columns if column not in CATEGORICAL]
    numeric_steps = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    category_steps = Pipeline([
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("encode", OneHotEncoder(handle_unknown="ignore")),
    ])
    return ColumnTransformer([
        ("numeric", numeric_steps, numbers),
        ("categories", category_steps, list(CATEGORICAL)),
    ])

def models(columns=FEATURES):
    logistic = LogisticRegression(max_iter=800, class_weight="balanced")
    forest = RandomForestClassifier(n_estimators=160, min_samples_leaf=8,
                                    class_weight="balanced_subsample", random_state=42, n_jobs=-1)
    return {
        "logistic": Pipeline([("preprocess", preprocess(columns)), ("model", logistic)]),
        "random_forest": Pipeline([("preprocess", preprocess(columns)), ("model", forest)]),
    }

def feature_drift(train,test):
    results={}
    for key in FEATURES:
        if key in CATEGORICAL:
            a=train[key].fillna('MISSING').value_counts(normalize=True);b=test[key].fillna('MISSING').value_counts(normalize=True)
            results[key]={'total_variation_distance':float(sum(abs(float(a.get(x,0))-float(b.get(x,0))) for x in set(a.index)|set(b.index))/2)}
        else:
            a=pd.to_numeric(train[key],errors='coerce');b=pd.to_numeric(test[key],errors='coerce')
            results[key]={'standardized_mean_shift':float(abs(b.mean()-a.mean())/a.std()) if a.std()>0 else None}
    return results
def validate_new_orders(path):
    frame=pd.read_csv(path)
    expected={'order_id','approved_at',*FEATURES};actual=set(frame.columns)
    if expected!=actual: raise ValueError(f'Input schema mismatch; missing={sorted(expected-actual)} unexpected={sorted(actual-expected)}')
    if frame.order_id.isna().any() or frame.order_id.duplicated().any(): raise ValueError('order_id must be unique and non-null')
    frame['approved_at']=pd.to_datetime(frame.approved_at,errors='raise')
    if frame.approved_at.isna().any(): raise ValueError('approved_at must not be null')
    for key in FEATURES:
        if key not in CATEGORICAL: frame[key]=pd.to_numeric(frame[key],errors='raise')
    return frame
def predict(input_path,model_path,output):
    import joblib
    saved=joblib.load(model_path) # Only load trusted artifacts.
    audit_features(saved['features'])
    if tuple(saved['features'])!=FEATURES: raise ValueError('Model feature schema differs from audited feature contract')
    headers = set(pd.read_csv(input_path, nrows=0).columns)
    if 'order_purchase_timestamp' in headers or 'customer_id' in headers:
        if not os.environ.get('DATABASE_URL'):
            raise ValueError('Raw orders require DATABASE_URL for the shared SQL feature query')
        engine = create_engine(os.environ['DATABASE_URL'])
        try:
            frame = raw_features(input_path, engine)
        finally:
            engine.dispose()
    else:
        frame = validate_new_orders(input_path)
    if frame.empty:
        pd.DataFrame(columns=['order_id','approved_at','risk_score','follow_up']).to_csv(output,index=False)
        return
    frame['risk_score']=saved['model'].predict_proba(frame[list(FEATURES)])[:,1]
    frame['follow_up']=select_top(frame.risk_score.to_numpy(),.10)
    frame.sort_values(['risk_score','order_id'],ascending=[False,True])[['order_id','approved_at','risk_score','follow_up']].to_csv(output,index=False)
def build_snapshot(engine,offline):
    years=pd.read_sql_query(text('SELECT DISTINCT EXTRACT(YEAR FROM order_approved_at)::int AS approval_year FROM olist.orders WHERE order_approved_at IS NOT NULL'),engine).approval_year.tolist()
    if not years: raise ValueError('No approved Olist orders')
    holidays=acquire_holidays(years,ROOT/'data'/'external',offline)
    with engine.begin() as con:
        con.execute(text('CREATE SCHEMA IF NOT EXISTS capstone'))
        con.execute(text('CREATE TABLE IF NOT EXISTS capstone.holidays(holiday_date date PRIMARY KEY,holiday_name text NOT NULL,source text NOT NULL)'))
        con.execute(text('TRUNCATE capstone.holidays'))
        for date,name,source in holidays:
            con.execute(text('INSERT INTO capstone.holidays VALUES (:d,:n,:s)'),{'d':date,'n':name,'s':source})
        query = feature_query('olist.orders')
        ddl = (ROOT/'sql'/'features.sql').read_text(encoding='utf-8')
        con.exec_driver_sql(ddl.replace('{feature_query}', query))
    with engine.connect() as con:
        return con.exec_driver_sql("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT * FROM capstone.feature_rows").scalar()
def run_training(engine,out):
    audit_features()
    cols=','.join(['order_id','approved_at',*FEATURES])
    features=pd.read_sql_query(text(f'SELECT {cols} FROM capstone.features ORDER BY approved_at,order_id'),engine,parse_dates=['approved_at'])
    labels=pd.read_sql_query(text("""
        SELECT o.order_id,MAX((r.review_score<=2)::int)::int negative,
        MAX(EXTRACT(EPOCH FROM (o.order_delivered_customer_date-o.order_approved_at))/86400.0)::float8 leaked_delivery_days,
        MAX((o.order_status='delivered')::int)::int leaked_delivered,
        MAX(EXTRACT(EPOCH FROM (o.order_delivered_carrier_date-o.order_approved_at))/86400.0)::float8 leaked_carrier_days,
        CASE WHEN count(*) = count(r.review_answer_timestamp)
             THEN MAX(r.review_answer_timestamp) END AS label_available_at
        FROM olist.orders o JOIN olist.order_reviews r ON r.order_id=o.order_id
        WHERE o.order_approved_at IS NOT NULL GROUP BY o.order_id
    """),engine)
    all_orders=features.merge(labels,on='order_id',how='left',validate='one_to_one')
    development, test, cutoff = temporal_split(all_orders)
    train = development.loc[development.label_available_at < pd.Timestamp(cutoff)].copy()
    if train.negative.nunique()!=2 or test.negative.nunique()!=2: raise ValueError('Both partitions require both labels')
    periods=development.approved_at.dt.to_period('M');last=periods.max()
    fit = development.loc[(periods < last) & (development.label_available_at < last.start_time)]
    valid = development.loc[periods == last].copy()
    valid.loc[valid.label_available_at >= pd.Timestamp(cutoff), 'negative'] = np.nan
    valid.loc[valid.label_available_at.isna(), 'negative'] = np.nan
    if fit.empty or valid.empty or fit.negative.nunique()!=2 or valid.negative.nunique()!=2:
        raise ValueError('Insufficient chronological development set')
    scores={};metrics={};validation={}
    for name,model in models().items():
        model.fit(fit[list(FEATURES)],fit.negative.astype(int))
        validation[name]=evaluate(valid.negative,model.predict_proba(valid[list(FEATURES)])[:,1])['recall']
        model.fit(train[list(FEATURES)],train.negative.astype(int))
        scores[name]=(model,model.predict_proba(test[list(FEATURES)])[:,1])
        metrics[name]={str(c):evaluate(test.negative,scores[name][1],c) for c in (.05,.10,.20)}
    baseline=test.approval_lag_hours.fillna(0).to_numpy()
    metrics['approval_delay_baseline']={str(c):evaluate(test.negative,baseline,c) for c in (.05,.10,.20)}
    winner = max(validation, key=validation.get)
    model, score = scores[winner]
    # Keep the family, training rows and hyperparameters fixed in the leakage experiment.
    leaked = ["leaked_delivery_days", "leaked_delivered", "leaked_carrier_days"]
    comparison_columns = list(FEATURES) + leaked
    comparison_model = models(comparison_columns)[winner]
    comparison_model.fit(train[comparison_columns], train.negative.astype(int))
    leaked_score = comparison_model.predict_proba(test[comparison_columns])[:, 1]
    metrics["intentionally_leaky_DO_NOT_DEPLOY"] = {"0.1": evaluate(test.negative, leaked_score)}
    # Refit the selected family with the holiday flag held constant.
    without_holiday = models()[winner]
    train_inputs = train[list(FEATURES)].assign(is_public_holiday=0)
    test_inputs = test[list(FEATURES)].assign(is_public_holiday=0)
    without_holiday.fit(train_inputs, train.negative.astype(int))
    holiday_control = without_holiday.predict_proba(test_inputs)[:, 1]
    metrics['without_holiday'] = {'0.1': evaluate(test.negative, holiday_control)}
    monthly={}
    for month,subset in test.groupby(test.approved_at.dt.to_period('M')):
        positions=test.index.get_indexer(subset.index)
        monthly[str(month)] = evaluate(subset.negative,score[positions]) if subset.negative.notna().any() else {'eligible_orders':len(subset),'n':0,'recall':None}
    # Operational quota is applied to ALL eligible orders, not just labeled orders.
    operation=features.loc[features.approved_at>=pd.Timestamp(f'{cutoff}-01')].copy()
    operation['risk_score']=model.predict_proba(operation[list(FEATURES)])[:,1]
    operation['follow_up']=select_top(operation.risk_score.to_numpy(),.10)
    operation.sort_values(['risk_score','order_id'],ascending=[False,True])[['order_id','approved_at','risk_score','follow_up']].to_csv(out/'follow_up_ranked.csv',index=False)
    import joblib
    joblib.dump({'model':model,'features':FEATURES,'cutoff':cutoff},out/'model.joblib')
    summary={'cutoff_month':cutoff,'training_rows':len(train),'evaluation_rows':len(test),'unreviewed_excluded_from_evaluation':int(all_orders.negative.isna().sum()),'model_selected':winner,'validation_month':str(last),'validation_recall_10pct':validation,'metrics':metrics,'leakage_recall_delta_at_10pct':metrics['intentionally_leaky_DO_NOT_DEPLOY']['0.1']['recall']-metrics[winner]['0.1']['recall'],'monthly':monthly,'last_month':monthly[max(monthly)],'drift':feature_drift(train,test),'operation_orders_ranked':len(operation)}
    (out/'evaluation.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
    return summary
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--raw-dir',type=Path,default=STAGE2/'data'/'raw');b.add_argument('--skip-load',action='store_true');b.add_argument('--offline',action='store_true');b.add_argument('--output',type=Path,default=ROOT/'artifacts')
    p=sub.add_parser('predict');p.add_argument('--input',type=Path,required=True);p.add_argument('--artifact',type=Path,default=ROOT/'artifacts'/'model.joblib');p.add_argument('--output',type=Path,default=ROOT/'artifacts'/'unseen_ranked.csv')
    args=parser.parse_args(argv)
    if args.command=='predict':
        args.output.parent.mkdir(parents=True,exist_ok=True);predict(args.input,args.artifact,args.output);return 0
    if not os.environ.get('DATABASE_URL'): parser.error('DATABASE_URL is required')
    args.output.mkdir(parents=True,exist_ok=True)
    timings={};start=time.perf_counter();engine=create_engine(os.environ['DATABASE_URL'],pool_pre_ping=True)
    try:
        if not args.skip_load:
            sys.path.insert(0,str(STAGE2/'src'))
            from database_performance.loader import apply_migrations
            from nyc311_factory.olist import ingest_orders
            t=time.perf_counter();apply_migrations(engine,include_indexes=True,include_retirements=True);timings['migrations_seconds']=time.perf_counter()-t
            t=time.perf_counter();manifest=ingest_orders(engine,args.raw_dir,args.output);timings['load_seconds']=time.perf_counter()-t
            (args.output/'ingestion_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        t=time.perf_counter();plan=build_snapshot(engine,args.offline);timings['feature_seconds']=time.perf_counter()-t
        (args.output/'feature_query_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
        t=time.perf_counter();summary=run_training(engine,args.output);timings['training_seconds']=time.perf_counter()-t
        with engine.connect() as con:
            summary['approved_timestamp_missing_excluded']=int(con.execute(text('SELECT count(*) FROM olist.orders WHERE order_approved_at IS NULL')).scalar())
        (args.output/'evaluation.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
    finally:
        engine.dispose();timings['total_seconds']=time.perf_counter()-start
        (args.output/'timings.json').write_text(json.dumps(timings,indent=2),encoding='utf-8')
    write_reports(args.output)
    print(json.dumps({'outputs':str(args.output),'timings':timings},indent=2));return 0
if __name__=='__main__': raise SystemExit(main())
