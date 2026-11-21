# What could the team know at approval?

| Column | First available | Evidence and hypothesis |
|---|---|---|
| approval_weekday | Approval event | Olist purchase or approval timestamp. Weekly differences in processing. |
| approval_month | Approval event | Olist purchase or approval timestamp. Seasonal pressure. |
| approval_hour | Approval event | Olist purchase or approval timestamp. Shift staffing. |
| approval_lag_hours | Approval event | Olist purchase or approval timestamp. Waiting for approval may frustrate buyers. |
| purchase_hour | Purchase event | Olist purchase or approval timestamp. Purchasing time may reflect different service windows. |
| purchase_weekday | Purchase event | Olist purchase or approval timestamp. Weekend purchases can wait for working days. |
| is_weekend | Approval event | Olist purchase or approval timestamp. Weekend staffing may affect handling. |
| is_public_holiday | Published holiday calendar | Brazil national holiday calendar. Historical corrections are possible. Holiday staffing may slow service. |
| customer_state | Checkout customer record | Order-specific customer ID links to the checkout address. Olist has no address edit log, so this assumes checkout geography is stable. Regional service differences. |
| customer_zip_region | Checkout customer record | Order-specific customer ID links to the checkout address. Olist has no address edit log, so this assumes checkout geography is stable. Regional delivery coverage. |
| prior_day_shipments | End of the previous calendar day | SQL counts only dated events one day strictly before approval. Missing days contribute zero. Recent handoff volume proxies warehouse load. |
| prior_day_deliveries | End of the previous calendar day | SQL counts only dated events one day strictly before approval. Missing days contribute zero. Recent delivery volume proxies network load. |
| prior_day_replies | End of the previous calendar day | SQL counts only dated events one day strictly before approval. Missing days contribute zero. Recent feedback volume proxies service activity. |
| prior_day_negatives | End of the previous calendar day | SQL counts only dated events one day strictly before approval. Missing days contribute zero. Recent negative feedback may flag system-wide disruption. |
| snapshot_available | Checkout snapshot observed at or before approval | A timestamped capture distinguishes observed zeros from missing history. |
| seller_count | Checkout snapshot observed at or before approval | Distinct sellers in the captured basket test coordination burden. |
| product_count | Checkout snapshot observed at or before approval | Distinct products in the captured basket test packing complexity. |
| authorized_payment_value | Checkout snapshot observed at or before approval | Captured authorized payment total tests order-value effects. |
| interstate_shipping | Checkout snapshot observed at or before approval | Captured seller and customer states test cross-state shipping risk. |

The leaky comparison deliberately uses delivery duration, carrier handoff duration and final delivery status. Each is only known after approval. No current-order review enters production. Distinct item sellers, catalog measurements and payment totals have no first-seen timestamps in the public export. They are excluded from the retrospective model. An approval-time capture of the basket, catalog and payment authorizations would permit a broader model.
