variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "project" {
  type    = string
  default = "finops-showback"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "owner" {
  type    = string
  default = "anuj"
}

variable "alert_email" {
  description = "Email that receives reports, budget and anomaly alerts. Confirm the SNS subscription email after the first apply."
  type        = string
}

variable "required_tags" {
  description = "Tag keys every resource must have."
  type        = list(string)
  default     = ["Team", "Environment", "Project", "Owner"]
}

# ---- Demo teams -------------------------------------------------------------
variable "teams" {
  description = "Fake teams whose resources are created and charged back."
  type = map(object({
    owner      = string
    budget_usd = number
  }))
  default = {
    team-payments = { owner = "priya", budget_usd = 2 }
    team-search   = { owner = "rahul", budget_usd = 2 }
  }
}

variable "demo_ec2_enabled" {
  description = "Create one t3.micro per team. Needed to test rightsizing; costs money if left running. Turn off when done."
  type        = bool
  default     = false
}

variable "create_untagged_test_resource" {
  description = "Create a 1 GiB untagged EBS volume so tag compliance has something to report."
  type        = bool
  default     = true
}

# ---- Budgets & anomaly detection -------------------------------------------
variable "monthly_budget_usd" {
  description = "Overall account budget."
  type        = number
  default     = 5
}

variable "team_budgets_enabled" {
  description = "Per-team budgets. The first 2 budgets in an account are free; each extra one costs about $0.02/day."
  type        = bool
  default     = true
}

variable "create_anomaly_monitor" {
  description = "Set false if your account already has an 'AWS services' anomaly monitor (AWS allows only one)."
  type        = bool
  default     = true
}

variable "anomaly_threshold_usd" {
  description = "Alert when an anomaly's total impact is at least this many dollars."
  type        = number
  default     = 1
}

variable "activate_cost_allocation_tags" {
  description = "Activate the required tags as cost allocation tags. Only works after AWS has seen the tags in billing data (24-48h after first tagged resource). Apply once with false, then flip to true."
  type        = bool
  default     = false
}

# ---- Lambda behaviour -------------------------------------------------------
variable "cleanup_dry_run" {
  description = "When true the cleanup Lambda only reports. Set false to actually delete."
  type        = bool
  default     = true
}

variable "volume_min_age_days" {
  type    = number
  default = 7
}

variable "ami_max_age_days" {
  type    = number
  default = 90
}

variable "rightsizing_cpu_threshold" {
  type    = number
  default = 10
}

variable "rightsizing_lookback_days" {
  type    = number
  default = 14
}

variable "showback_lookback_days" {
  type    = number
  default = 7
}

variable "schedules" {
  description = "EventBridge schedule per Lambda (times in UTC)."
  type        = map(string)
  default = {
    showback_report  = "cron(30 3 ? * MON *)" # Mondays 09:00 IST
    tag_compliance   = "cron(0 4 ? * MON *)"  # Mondays 09:30 IST
    resource_cleanup = "cron(30 4 * * ? *)"   # Daily 10:00 IST
    rightsizing      = "cron(0 5 ? * MON *)"  # Mondays 10:30 IST
  }
}
