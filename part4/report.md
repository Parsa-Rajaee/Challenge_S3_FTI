# Choosing orders for customer follow-up

The decision happens when payment approval is recorded. A support agent needs a short list before a complaint arrives. The supplied outcome measures whether a customer left a negative review. It cannot tell us whether a call would have prevented one. Reach and capacity therefore matter more here than how often the model predicts the majority class.

## Decisions and evidence

- **Who to rank.** Rank all approvals. Learn from observed reviews. Unknown outcomes consume team capacity and limit measured precision.
- **When to score.** Use approval as requested. Exclude missing approvals. We cannot serve orders without a decision timestamp.
- **What is negative.** Any score of one or two marks the order negative. One bad experience outweighs a later favorable review.
- **Where to split.** Hold out the last portion of complete observed month labels by approval month. Use the remaining period for development. A sparse last month makes recall unstable.
- **When to learn.** Fit on orders whose last recorded answer precedes the training boundary. Slow responses reduce training coverage.
- **What to join.** Use prior-day events and checkout geography. Exclude unversioned payment, catalog and seller attributes. We lose potentially useful commercial signals.
- **Where to compute.** Use the same PostgreSQL SELECT for historical and incoming orders. Raw scoring requires the reference database.
- **How to select a model.** Compare logistic regression and random forest in up to three development months. Each fit uses earlier orders with outcomes known before that month. Within the validation month, reserve capacity for all approvals and count only outcomes known by the next month. Pool the negative orders found across those separate queues. This gives a busier month more weight when it has more known negatives.
- **How many to contact.** Round down at each requested capacity. Ties go to the earliest approval, then the lowest order ID. The queue and the quota use the same ranking. Fewer than ten orders result in zero follow-ups at 10%.
- **How to handle holidays.** Compare the selected family with an otherwise identical fit holding the holiday flag constant. A sparse calendar may add no measurable value.
- **How to ingest.** Use a Stage 1 source adapter, Stage 2 Olist contracts and transactional quarantine, and Stage 1 manifest utilities. Clean rebuilds require a dedicated database.
- **How to measure speed.** Measure the full feature SELECT with EXPLAIN ANALYZE and time historical aggregation separately inside the feature stage. A warm plan and a cold build measure different costs.

## Temporal leakage

The availability table in feature_audit.md is independent of the model's Python list. The integration test passes a future delivery date through the raw prediction command and checks that every score stays identical. The deliberately leaky comparison model additionally uses elapsed time until carrier handoff, elapsed time until delivery, and final delivered status. Compare recall at the same quota in artifacts/measured_results.md. Both models use the same family and hyperparameters.

## What we rejected

The original implementation used freight divided by item price as the baseline and current-order payment and seller information in both models. The export cannot establish when these attributes were first observable. A longer approval delay is a weaker but reproducible baseline. We also rejected rounding the contact allowance up. A team with capacity for ten percent of nine orders cannot contact one order without exceeding its limit.

## Performance, drift and the last month

The solution notebook shows confusion counts and the capacity trade-off. The exploration notebook shows volume, review coverage, calendar ablation and the latest month's negative-review count. A month with one bad review can move from zero to full recall on one order. Compare volume and changes in the inputs before drawing conclusions about geography or workload. Over six months, incomplete event history or a change in who leaves reviews could move both rankings and measured recall. Track missing states, the last available event day, review coverage, recall after reviews mature, and contact counts by month.

## Limits and follow-up

The assignment requests seller, product, payment and geography inputs. Checkout geography uses the order-specific customer record. Seller, product and payment features require an observed checkout snapshot because the public tables lack first-seen timestamps. After loading recent events, refresh the daily aggregates before live scoring. The refresh does not train a new model, so changes in the order mix still warrant a separate evaluation. National holidays omit local closures. Offline replay needs a previously populated calendar cache.

With two further days, investigate intervention effectiveness on a randomized group of eligible orders, and obtain independently timestamped checkout and payment events. Record a baseline on the actual evaluation machine and repeat the SQL timing after a cold database restart.

## AI usage

An AI assistant drafted and revised the implementation, tests and analysis text. The notebooks contain the measured results from an executed public-data run.

## Timestamped commercial inputs

The optional checkout snapshot contract adds seller and product counts, payment value and cross-state shipping. Its source must capture those facts at the stated time. The public benchmark has zero timestamped coverage, so those inputs cannot support a retrospective performance claim. Coverage is recorded in evaluation.json.

## Verified public benchmark

Across February–April 2018 validation, pooled recall at 10% capacity was 8.98% for logistic regression and 8.90% for random forest. Random forest led in March. The final holdout starts in May 2018 and contains 26,027 approvals, 25,892 with at least one review. Contacting 5%, 10% and 20% found 6.4%, 12.8% and 23.9% of orders with known negative reviews. At 10%, approval delay alone found 10.22%. The model found 369 of 2,878 negative outcomes. Future information raised recall by 18.97 percentage points. The holiday flag decreased recall by 0.14 points. September had one approved order and one negative review. The 10% hard cap allowed zero contacts.

The full feature query took 291.0 ms and the build took 137.4 seconds in the recorded public run. Both passed their runtime budgets. The full raw-order replay reproduced all holdout scores and flags after removing post-approval delivery fields. The saved solution notebook displays timings, replay counts and the full confusion counts.
