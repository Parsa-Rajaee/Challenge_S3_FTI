"""Build, evaluate, and score Olist orders. Outputs are evidence, not invented metrics."""
import argparse
import json
import os
import time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sqlalchemy import create_engine,text
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from .core import FEATURES, CATEGORICAL, audit_features, evaluate, rank_orders, temporal_split
from .external import acquire_holidays
from .raw_orders import raw_features, feature_query, ensure_calendar
from .reporting import write_reports
from .snapshots import load_snapshots
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
    frame = pd.read_csv(path, dtype={name: str for name in ("order_id", *CATEGORICAL)})
    expected={'order_id','approved_at',*FEATURES};actual=set(frame.columns)
    if expected!=actual: raise ValueError(f'Input schema mismatch; missing={sorted(expected-actual)} unexpected={sorted(actual-expected)}')
    if frame.order_id.isna().any() or frame.order_id.duplicated().any(): raise ValueError('order_id must be unique and non-null')
    frame['approved_at']=pd.to_datetime(frame.approved_at,errors='raise')
    if frame.approved_at.isna().any(): raise ValueError('approved_at must not be null')
    for key in FEATURES:
        if key not in CATEGORICAL: frame[key]=pd.to_numeric(frame[key],errors='raise')
    return frame
def predict(input_path, model_path, output, offline=False):
    saved=joblib.load(model_path) # Only load trusted artifacts.
    audit_features(saved['features'])
    if tuple(saved['features'])!=FEATURES: raise ValueError('Model feature schema differs from audited feature contract')
    headers = set(pd.read_csv(input_path, nrows=0).columns)
    if 'order_purchase_timestamp' in headers or 'customer_id' in headers:
        if not os.environ.get('DATABASE_URL'):
            raise ValueError('Raw orders require DATABASE_URL for the shared SQL feature query')
        engine = create_engine(os.environ['DATABASE_URL'])
        try:
            frame = raw_features(input_path, engine, offline)
        finally:
            engine.dispose()
    else:
        frame = validate_new_orders(input_path)
    scores = np.array([]) if frame.empty else saved["model"].predict_proba(frame[list(FEATURES)])[:, 1]
    rank_orders(frame, scores).to_csv(output, index=False)


def refresh_reference(engine, snapshots=None):
    """Refresh live scoring inputs atomically."""
    with engine.begin() as connection:
        connection.execute(text("REFRESH MATERIALIZED VIEW capstone.shipping_days"))
        if snapshots is not None:
            load_snapshots(connection, snapshots)


def build_snapshot(engine, offline, snapshots=None, *, preserve_snapshots=False):
    years=pd.read_sql_query(text('SELECT DISTINCT EXTRACT(YEAR FROM order_approved_at)::int AS approval_year FROM olist.orders WHERE order_approved_at IS NOT NULL'),engine).approval_year.tolist()
    if not years: raise ValueError('No approved Olist orders')
    holidays=acquire_holidays(years,ROOT/'data'/'external',offline)
    with engine.begin() as con:
        con.execute(text('CREATE SCHEMA IF NOT EXISTS capstone'))
        load_snapshots(con, snapshots, preserve_existing=preserve_snapshots)
        con.execute(text('CREATE TABLE IF NOT EXISTS capstone.holidays(holiday_date date PRIMARY KEY,holiday_name text NOT NULL,source text NOT NULL)'))
        con.execute(text('TRUNCATE capstone.holidays'))
        for date,name,source in holidays:
            con.execute(text('INSERT INTO capstone.holidays VALUES (:d,:n,:s)'),{'d':date,'n':name,'s':source})
        query = feature_query('olist.orders')
        ddl = (ROOT/'sql'/'features.sql').read_text(encoding='utf-8')
        con.exec_driver_sql(ddl.replace('{feature_query}', query))
    with engine.connect() as con:
        return con.exec_driver_sql("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT * FROM capstone.feature_rows").scalar()


def validate_models(development):
    """Evaluate recent development months in separate contact batches."""
    periods = development.approved_at.dt.to_period("M")
    folds = {}
    for month in sorted(periods.unique())[-3:]:
        fit = development.loc[
            (periods < month) & (development.label_available_at < month.start_time)
        ]
        valid = development.loc[periods == month].copy()
        mature = valid.label_available_at < (month + 1).start_time
        valid["negative"] = valid.negative.where(mature)
        if fit.negative.nunique() < 2 or valid.negative.eq(1).sum() == 0:
            continue
        results = {}
        for name, model in models().items():
            model.fit(fit[list(FEATURES)], fit.negative.astype(int))
            scores = model.predict_proba(valid[list(FEATURES)])[:, 1]
            results[name] = evaluate(valid.negative, scores)
        folds[str(month)] = {"fit_rows": len(fit), "models": results}

    if not folds:
        raise ValueError("Insufficient chronological development set")
    validation = {}
    for name in next(iter(folds.values()))["models"]:
        results = [fold["models"][name] for fold in folds.values()]
        true_positives = sum(result["confusion_matrix_tn_fp_fn_tp"][-1] for result in results)
        validation[name] = true_positives / sum(result["positives"] for result in results)
    return validation, folds


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
    validation, folds = validate_models(development)
    winner = max(validation, key=validation.get)
    scores = {}
    metrics = {}
    for name,model in models().items():
        model.fit(train[list(FEATURES)],train.negative.astype(int))
        scores[name]=(model,model.predict_proba(test[list(FEATURES)])[:,1])
        metrics[name]={str(c):evaluate(test.negative,scores[name][1],c) for c in (.05,.10,.20)}
    baseline=test.approval_lag_hours.fillna(0).to_numpy()
    metrics['approval_delay_baseline']={str(c):evaluate(test.negative,baseline,c) for c in (.05,.10,.20)}
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
    monthly = {}
    for month, subset in test.groupby(test.approved_at.dt.to_period("M")):
        positions = test.index.get_indexer(subset.index)
        result = evaluate(subset.negative, score[positions])
        result["approval_delay_recall"] = evaluate(subset.negative, baseline[positions])["recall"]
        monthly[str(month)] = result
    ranked = rank_orders(test, score)
    ranked.to_csv(out / "follow_up_ranked.csv", index=False)
    joblib.dump({'model':model,'features':FEATURES,'cutoff':cutoff},out/'model.joblib')
    return {
        "snapshot_coverage": float(features.snapshot_available.mean()),
        "cutoff_month": cutoff,
        "training_rows": len(train),
        "evaluation_rows": len(test),
        "unreviewed_excluded_from_evaluation": int(test.negative.isna().sum()),
        "model_selected": winner,
        "validation_month": max(folds),
        "validation_recall_10pct": validation,
        "validation_folds": folds,
        "metrics": metrics,
        "leakage_recall_delta_at_10pct": (
            metrics["intentionally_leaky_DO_NOT_DEPLOY"]["0.1"]["recall"]
            - metrics[winner]["0.1"]["recall"]
        ),
        "monthly": monthly,
        "last_month": monthly[max(monthly)],
        "drift": feature_drift(train, test),
        "operation_orders_ranked": len(ranked),
    }
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--raw-dir',type=Path,default=STAGE2/'data'/'raw');b.add_argument('--skip-load',action='store_true');b.add_argument('--offline',action='store_true');b.add_argument('--output',type=Path,default=ROOT/'artifacts')
    b.add_argument('--checkout-snapshots', type=Path, help='Optional genuinely timestamped seller, product, payment and geography snapshots')
    p=sub.add_parser('predict');p.add_argument('--input',type=Path,required=True);p.add_argument('--artifact',type=Path,default=ROOT/'artifacts'/'model.joblib');p.add_argument('--output',type=Path,default=ROOT/'artifacts'/'unseen_ranked.csv')
    p.add_argument("--offline", action="store_true", help="Use cached holiday calendars for raw orders")
    refresh = sub.add_parser("refresh-reference", help="Update live scoring inputs without training")
    refresh.add_argument("--checkout-snapshots", type=Path, help="Replace the stored snapshot history")
    args=parser.parse_args(argv)
    if args.command=='predict':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        predict(args.input, args.artifact, args.output, args.offline)
        return 0
    if not os.environ.get('DATABASE_URL'): parser.error('DATABASE_URL is required')
    if args.command == "refresh-reference":
        engine = create_engine(os.environ["DATABASE_URL"])
        try:
            refresh_reference(engine, args.checkout_snapshots)
        finally:
            engine.dispose()
        print("Refreshed approval-time scoring inputs.")
        return 0
    args.output.mkdir(parents=True,exist_ok=True)
    timings={};start=time.perf_counter();engine=create_engine(os.environ['DATABASE_URL'],pool_pre_ping=True)
    try:
        if not args.skip_load:
            from database_performance.loader import apply_migrations
            from nyc311_factory.olist import ingest_orders
            t=time.perf_counter();apply_migrations(engine,include_indexes=True,include_retirements=True);timings['migrations_seconds']=time.perf_counter()-t
            t=time.perf_counter();manifest=ingest_orders(engine,args.raw_dir,args.output);timings['load_seconds']=time.perf_counter()-t
            (args.output/'ingestion_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        t = time.perf_counter()
        plan = build_snapshot(engine, args.offline, args.checkout_snapshots, preserve_snapshots=args.skip_load)
        timings["feature_seconds"] = time.perf_counter() - t
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
