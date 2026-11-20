INSERT INTO credit.borrowers
    (applicant_id, serious_dlqin_2yrs, revolving_utilization_of_unsecured_lines,
     age, number_of_time30_59_days_past_due_not_worse, debt_ratio,
     monthly_income, number_of_open_credit_lines_and_loans,
     number_of_times90_days_late, number_real_estate_loans_or_lines,
     number_of_time60_89_days_past_due_not_worse, number_of_dependents)
VALUES
    (:applicant_id, :serious_dlqin_2yrs, :revolving_utilization_of_unsecured_lines,
     :age, :number_of_time30_59_days_past_due_not_worse, :debt_ratio,
     :monthly_income, :number_of_open_credit_lines_and_loans,
     :number_of_times90_days_late, :number_real_estate_loans_or_lines,
     :number_of_time60_89_days_past_due_not_worse, :number_of_dependents)
ON CONFLICT (applicant_id) DO UPDATE SET
    serious_dlqin_2yrs = EXCLUDED.serious_dlqin_2yrs,
    revolving_utilization_of_unsecured_lines = EXCLUDED.revolving_utilization_of_unsecured_lines,
    age = EXCLUDED.age,
    number_of_time30_59_days_past_due_not_worse = EXCLUDED.number_of_time30_59_days_past_due_not_worse,
    debt_ratio = EXCLUDED.debt_ratio,
    monthly_income = EXCLUDED.monthly_income,
    number_of_open_credit_lines_and_loans = EXCLUDED.number_of_open_credit_lines_and_loans,
    number_of_times90_days_late = EXCLUDED.number_of_times90_days_late,
    number_real_estate_loans_or_lines = EXCLUDED.number_real_estate_loans_or_lines,
    number_of_time60_89_days_past_due_not_worse = EXCLUDED.number_of_time60_89_days_past_due_not_worse,
    number_of_dependents = EXCLUDED.number_of_dependents
