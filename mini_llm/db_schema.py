SCHEMA_TEXT = """
employees(
  id,
  full_name,
  email,
  phone,
  department_id,
  position_id,
  salary_base,
  status,
  role,
  created_at
)

departments(
  id,
  name,
  description
)

positions(
  id,
  title,
  base_salary_range
)

payroll(
  id,
  employee_id,
  month,
  year,
  salary_base,
  bonus,
  deductions,
  total_salary,
  status
)

payroll_records(
  id,
  employee_id,
  payroll_month,
  work_days_actual,
  ot_hours,
  salary_base,
  allowance_total,
  ot_total_pay,
  bonus_total,
  gross_income,
  bhxh_amount,
  bhyt_amount,
  bhtn_amount,
  pit_tax_amount,
  advance_amount,
  penalty_amount,
  net_pay,
  status,
  calculation_date
)

attendances(
  id,
  employee_id,
  date,
  check_in_time,
  check_out_time,
  is_late,
  is_early_leave,
  status,
  created_at,
  updated_at
)

leave_requests(
  id,
  employee_id,
  leave_type_id,
  start_date,
  end_date,
  total_days,
  reason,
  status,
  created_at
)

leave_types(
  id,
  name
)

employee_allowances(
  id,
  employee_id,
  allowance_name,
  amount,
  is_taxable
)

chatbot_intents(
  id,
  intent_tag,
  description
)

chatbot_kb(
  id,
  question,
  answer,
  intent_id
)

chatbot_logs(
  id,
  employee_id,
  user_message,
  bot_response,
  detected_intent,
  confidence_score,
  created_at
)

reports(
  id,
  report_name,
  type,
  category,
  size_mb,
  status,
  created_at,
  file_path
)

v_attendance_daily(
  id,
  employee_id,
  date,
  check_in_time,
  check_out_time,
  is_late,
  is_early_leave,
  status,
  working_hours,
  working_day
)

v_attendance_monthly(
  employee_id,
  year,
  month,
  total_records,
  working_days,
  total_working_hours,
  late_days,
  early_leave_days,
  absent_days
)

v_payroll_from_attendance(
  employee_id,
  full_name,
  year,
  month,
  salary_base,
  paid_days,
  calculated_salary
)
"""