# ---- Overall account budget -------------------------------------------------
resource "aws_budgets_budget" "account" {
  name         = "${var.project}-account-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

# ---- Per-team budgets, filtered by the Team cost allocation tag ------------
resource "aws_budgets_budget" "team" {
  for_each = var.team_budgets_enabled ? var.teams : {}

  name         = "${var.project}-${each.key}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(each.value.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = [format("user:Team$%s", each.key)]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}

# ---- Cost Anomaly Detection (free) -----------------------------------------
resource "aws_ce_anomaly_monitor" "services" {
  count             = var.create_anomaly_monitor ? 1 : 0
  name              = "${var.project}-services"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "email" {
  count            = var.create_anomaly_monitor ? 1 : 0
  name             = "${var.project}-anomaly-alerts"
  frequency        = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.services[0].arn]

  subscriber {
    type    = "EMAIL"
    address = var.alert_email
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(var.anomaly_threshold_usd)]
    }
  }
}

# ---- Cost allocation tags ---------------------------------------------------
# Makes Team/Environment/Project/Owner usable in Cost Explorer and Budgets.
resource "aws_ce_cost_allocation_tag" "required" {
  for_each = var.activate_cost_allocation_tags ? toset(var.required_tags) : toset([])
  tag_key  = each.value
  status   = "Active"
}
