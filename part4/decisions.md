# Capstone decisions

### Who to rank

All approved orders or reviewed orders only? Rank all approvals. Learn from observed reviews. Unknown outcomes consume team capacity and limit measured precision.

### When to score

Purchase, approval or shipment? Use approval as requested. Exclude missing approvals. We cannot serve orders without a decision timestamp.

### What is negative

First, latest or any review? Any score of one or two marks the order negative. One bad experience outweighs a later favorable review.

### Where to split

Random rows or calendar boundary? Hold out the last portion of complete observed month labels by approval month. Use the remaining period for development. A sparse last month makes recall unstable.

### When to learn

All historical outcomes or only mature labels? Fit on orders whose last recorded answer precedes the training boundary. Slow responses reduce training coverage.

### What to join

Archived basket or dated events? Use prior-day events and checkout geography. Exclude unversioned payment, catalog and seller attributes. We lose potentially useful commercial signals.

### Where to compute

Independent Python and SQL transformations or one query? Use the same PostgreSQL SELECT for historical and incoming orders. Raw scoring requires the reference database.

### How to select a model

Holdout tuning, a single validation month or rolling validation? Use up to three development months and pool known negatives found at each month's quota. The wider comparison gauges whether a family depends on a single month's mix. The strict label cutoff leaves late reviews unresolved during validation.

### How many to contact

Round up or down? Round down at each requested capacity. Ties favor the earliest approval, then the lowest order ID. Fewer than ten orders result in zero follow-ups at 10%.

### How to handle holidays

Always assume a benefit or test it? Compare the selected family with an otherwise identical fit holding the holiday flag constant. A sparse calendar may add no measurable value.

### How to ingest

Create a parallel loader or reuse both packages? Use a Stage 1 source adapter, Stage 2 Olist contracts and transactional quarantine, and Stage 1 manifest utilities. Clean rebuilds require a dedicated database.

### How to measure speed

Read a limited snapshot or time feature construction? Measure the full feature SELECT with EXPLAIN ANALYZE and time historical aggregation separately inside the feature stage. A warm plan and a cold build measure different costs.
