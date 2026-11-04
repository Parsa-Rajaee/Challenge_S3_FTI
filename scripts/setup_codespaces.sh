#!/usr/bin/env bash
set -e

echo "=========================================================="
echo " Starting GitHub Codespaces Setup for Season 3 Project    "
echo "=========================================================="

echo ">>> [1/5] Installing and starting PostgreSQL service..."
sudo apt-get update -y
sudo apt-get install -y postgresql postgresql-contrib
sudo service postgresql start

echo ">>> [2/5] Configuring PostgreSQL role and databases..."
sudo -u postgres psql -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'season3') THEN CREATE ROLE season3 WITH SUPERUSER LOGIN PASSWORD '1234'; END IF; END \$\$;"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = 'olist'" | grep -q 1 || sudo -u postgres createdb -O season3 olist
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = 'olist_test'" | grep -q 1 || sudo -u postgres createdb -O season3 olist_test

export DATABASE_URL="postgresql+psycopg2://season3:1234@localhost:5432/olist"
export PGPASSWORD="1234"

echo ">>> [3/5] Installing Python packages and dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e ".[database]"

if [ -f "part2/stage-2-database-performance/requirements.txt" ]; then
    echo "Installing Part 2 packages..."
    python -m pip install -r part2/stage-2-database-performance/requirements.txt
    python -m pip install -e ./part2/stage-2-database-performance
fi

if [ -f "part3/stage-3-machine-learning/requirements.txt" ]; then
    echo "Installing Part 3 packages..."
    python -m pip install -r part3/stage-3-machine-learning/requirements.txt
    python -m pip install -e ./part3/stage-3-machine-learning
fi

echo ">>> [4/5] Running Part 2 SQL migrations..."
if [ -d "part2/stage-2-database-performance/sql/migrations" ]; then
    for f in part2/stage-2-database-performance/sql/migrations/*.sql; do
        echo "Executing $f..."
        psql -h localhost -U season3 -d olist -f "$f" >/dev/null 2>&1 || true
    done
fi

echo ">>> [5/5] Ingesting Part 3 credit data into PostgreSQL..."
if [ -f "part3/stage-3-machine-learning/data/raw/cs-training.csv" ]; then
    python -m nyc311_factory --load-credit-csv part3/stage-3-machine-learning/data/raw/cs-training.csv
fi

echo "=========================================================="
echo " Codespaces setup finished successfully!                  "
echo " PostgreSQL is running at localhost:5432/olist            "
echo " You can open and run solution.ipynb or run pytest now!   "
echo "=========================================================="
