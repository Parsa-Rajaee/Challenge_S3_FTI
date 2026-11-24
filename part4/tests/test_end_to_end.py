"""A disposable PostgreSQL database is required for the full raw-file path."""
import csv
import json
import os
from datetime import datetime, timedelta
from uuid import UUID
import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from capstone import runner
from capstone.core import FEATURES, evaluate
from database_performance.schema import DATASETS

def test_unreviewed_orders_consume_capacity():
    labels = [None, 1] + [0] * 8
    result = evaluate(labels, list(range(10, 0, -1)))
    assert result["total_flagged"] == 1
    assert result["recall"] == 0

def test_tiny_batch_never_exceeds_budget():
    from capstone.core import select_top
    assert not select_top([0.9] * 9).any()

def test_audit_matches_independent_contract():
    from pathlib import Path
    audit = Path(__file__).resolve().parents[1] / "feature_audit.md"
    columns = [line.split("|")[1].strip() for line in audit.read_text().splitlines() if line.startswith("| ")]
    assert set(FEATURES) == set(columns[1:])

def test_raw_to_ranked(tmp_path, monkeypatch):
    url = os.environ.get("CAPSTONE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires a dedicated empty PostgreSQL database")
    engine = create_engine(url)
    with engine.connect() as con:
        assert con.execute(text("SELECT to_regnamespace('olist')")).scalar() is None
    monkeypatch.setenv("DATABASE_URL", url)
    raw = tmp_path / "raw"
    raw.mkdir()
    tables = {table.name: [] for table in DATASETS}
    uid = lambda i: UUID(int=i).hex
    tables["customers"].append([uid(1), uid(2), "01000", "Sao Paulo", "SP"])
    for i in range(120):
        purchase = datetime(2017, 1 + i // 20, 1 + i % 20, 8)
        approval = purchase + timedelta(hours=1)
        answer = datetime(2017, 3, 2) if i == 21 else approval
        tables["orders"].append([uid(i+10),uid(1),"delivered",purchase,approval,approval,approval,approval])
        tables["order_reviews"].append([uid(i+500),uid(i+10),1 if i % 3 == 0 else 5,"","",approval,answer])
    for table in DATASETS:
        with (raw / table.filename).open("w",newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow([field.source_name for field in table.fields])
            writer.writerows(tables[table.name])
    monkeypatch.setattr(runner, "acquire_holidays", lambda *args: [])
    monkeypatch.setattr("capstone.raw_orders.acquire_holidays", lambda *args: [])
    out = tmp_path / "out"
    capture = tmp_path / "captures.csv"
    capture.write_text("order_id,observed_at,seller_count,product_count,observed_payment_value,interstate_shipping\n"
                       + f"{uid(10)},2017-01-01 08:30:00,1,2,50,0\n"
                       + f"{uid(10)},2017-01-01 10:00:00,9,9,999,1\n")
    runner.main(["build","--raw-dir",str(raw),"--output",str(out),"--checkout-snapshots",str(capture)])
    with engine.connect() as connection:
        row = connection.execute(text("SELECT snapshot_available, product_count FROM capstone.features WHERE order_id=:id"),
                                 {"id":uid(10)}).one()
        assert tuple(row) == (1,2)
        assert connection.execute(text("SELECT sum(snapshot_available) FROM capstone.features")).scalar() == 1
    unseen = pd.read_csv(raw / "olist_orders_dataset.csv",dtype=str).iloc[-20:].copy()
    unseen["order_id"] = [uid(1000+i) for i in range(20)]
    unseen["order_status"] = "approved"
    unseen["order_delivered_customer_date"] = ""
    path = tmp_path / "new.csv"
    unseen.to_csv(path,index=False)
    args = ["predict","--input",str(path),"--artifact",str(out/"model.joblib"),"--output",str(out/"new.csv")]
    runner.main(args)
    result = pd.read_csv(out/"new.csv")
    assert len(result) == 20 and result.follow_up.sum() == 2
    assert result.risk_score.is_monotonic_decreasing
    unseen["order_delivered_customer_date"] = "2030-12-01"
    unseen.to_csv(path,index=False)
    runner.main(args)
    pd.testing.assert_frame_equal(result, pd.read_csv(out/"new.csv"))
    evaluation = json.loads((out / "evaluation.json").read_text())
    assert evaluation["training_rows"] > 0
    folds = evaluation["validation_folds"]
    assert list(folds) == ["2017-02", "2017-03", "2017-04"]
    assert folds["2017-02"]["models"]["logistic"]["n"] == 19
    assert folds["2017-03"]["fit_rows"] == 39
    assert folds["2017-04"]["fit_rows"] == 60

    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE olist.orders SET order_delivered_carrier_date = '2017-01-02 12:00'
            WHERE order_id = :order_id
        """), {"order_id": uid(10)})

    # A malformed replacement should roll the reference refresh back as well.
    invalid_capture = tmp_path / "invalid.csv"
    invalid_capture.write_text(capture.read_text() + "malformed\n")
    with pytest.raises(ValueError, match="Invalid checkout snapshot on line 4"):
        runner.main(["refresh-reference", "--checkout-snapshots", str(invalid_capture)])
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT shipments FROM capstone.shipping_days WHERE day = '2017-01-01'"
        )).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM capstone.checkout_snapshots")).scalar_one() == 2

    runner.main(["refresh-reference"])
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT shipments FROM capstone.shipping_days WHERE day = '2017-01-01'"
        )).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM capstone.checkout_snapshots")).scalar_one() == 2

    replacement = tmp_path / "replacement.csv"
    replacement.write_text(capture.read_text().splitlines()[0] + "\n"
                           + f"{uid(10)},2017-01-01 08:45:00,1,3,60,0\n")
    runner.main(["refresh-reference", "--checkout-snapshots", str(replacement)])
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT product_count FROM capstone.feature_rows WHERE order_id = :id"
        ), {"id": uid(10)}).scalar_one() == 3

def test_calendar_quarantines_wrong_country(tmp_path):
    from nyc311_factory.holidays import acquire_holidays
    rows = [
        {"date":"2018-01-01","name":"New Year","countryCode":"BR","global":True},
        {"date":"2018-02-01","name":"Wrong source","countryCode":"US"},
    ]
    (tmp_path / "holidays_br_2018.json").write_text(json.dumps(rows))
    assert acquire_holidays([2018], tmp_path, offline=True) == [("2018-01-01","New Year","Nager.Date")]
    manifest = json.loads((tmp_path / "manifest_2018.json").read_text())
    assert manifest["accepted_records"] == manifest["quarantined_records"] == 1
