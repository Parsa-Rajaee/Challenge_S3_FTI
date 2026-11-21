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
- **How to select a model.** Choose by validation recall at the operational quota before examining test outcomes. A single validation month can favor an unstable family.
- **How many to contact.** Round down at each requested capacity. Stable input order breaks ties. Fewer than ten orders result in zero follow-ups at 10%.
- **How to handle holidays.** Compare the selected family with an otherwise identical fit holding the holiday flag constant. A sparse calendar may add no measurable value.
- **How to ingest.** Use a Stage 1 source adapter, Stage 2 Olist contracts and transactional quarantine, and Stage 1 manifest utilities. Clean rebuilds require a dedicated database.
- **How to measure speed.** Measure the full feature SELECT with EXPLAIN ANALYZE and time historical aggregation separately inside the feature stage. A warm plan and a cold build measure different costs.

## Temporal leakage

The availability table in feature_audit.md is independent of the model's Python list. The integration test passes a future delivery date through the raw prediction command and checks that every score stays identical. The deliberately leaky comparison model additionally uses elapsed time until carrier handoff, elapsed time until delivery, and final delivered status. Compare recall at the same quota in artifacts/measured_results.md. Both models use the same family and hyperparameters.

## What we rejected

The original implementation used freight divided by item price as the baseline and current-order payment and seller information in both models. The export cannot establish when these attributes were first observable. A longer approval delay is a weaker but reproducible baseline. We also rejected rounding the contact allowance up. A team with capacity for ten percent of nine orders cannot contact one order without exceeding its limit.

## Performance, drift and the last month

Run the system notebook to inspect exact confusion counts, capacity trade-offs, review coverage, calendar ablation and the latest month's negative-review count. A month with one bad review can move from zero to full recall on one order. Compare its volume and the largest changes in inputs before attributing a loss to geography or workload. This observational comparison cannot establish cause. Over six months, incomplete reference history or a change in who leaves reviews could move both rankings and reported success. Monitor missing states, last available event day, reviewed fraction, recalls after reviews mature and monthly alert counts.

## Limits and follow-up

The assignment requests seller, product, payment and geography inputs. Checkout geography is used, but the public tables cannot certify when each seller, product or payment field was recorded. Obtain versioned approval-time snapshots before admitting those fields. Daily event features need recent events in the scoring database. A frozen installation faced with future orders can silently see zero activity. National holidays omit local closures. Offline replay needs a previously populated calendar cache.

With two further days, investigate intervention effectiveness on a randomized group of eligible orders, and obtain independently timestamped checkout and payment events. Record a baseline on the actual evaluation machine and repeat the SQL timing after a cold database restart.

## AI usage

An AI assistant drafted the implementation, tests and analysis text. The recorded run produces the measured results. No student-authored revisions or private evaluator results are claimed.

## Timestamped commercial inputs

The optional checkout snapshot contract adds seller and product counts, payment authorization value and cross-state shipping. Its source must capture those facts at the stated time. The public benchmark has zero timestamped coverage, so those inputs cannot support a retrospective performance claim. Coverage is recorded in evaluation.json.

## First verified public benchmark

In the approval-time model run with the May 2018 cutoff, contacting 5%, 10% and 20% found 6.3%, 12.9% and 23.9% of known negative reviews. At 10%, approval delay alone found 10.22%. Future information inflated recall by 18.97 percentage points. The holiday signal reduced recall by 0.07 points. The last month had only one approved order and one negative review. A 10% hard cap allowed no call, so the latest-month recall was zero by construction. This result cannot establish that customers or the model changed.

The full feature query took 148 ms and the build 73.6 seconds on the hosted runner. These measurements describe the linked run before optional timestamped commercial inputs. Later runs regenerate both numbers, the confusion counts and the executed notebooks.

[Benchmark run and executed notebooks](https://github.com/Parsa-Rajaee/Challenge_S3_FTI/actions/runs/44893656824)
