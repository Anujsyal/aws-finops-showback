# All four Lambdas are defined from one map: code location, schedule,
# environment variables and a least-privilege IAM policy for each.

locals {
  common_env = {
    REPORT_BUCKET = aws_s3_bucket.reports.bucket
    SNS_TOPIC_ARN = aws_sns_topic.alerts.arn
  }

  lambdas = {
    showback_report = {
      description = "Weekly per-team cost showback from Cost Explorer"
      timeout     = 60
      env = {
        COST_TAG_KEY  = "Team"
        LOOKBACK_DAYS = tostring(var.showback_lookback_days)
      }
      actions = ["ce:GetCostAndUsage"]
    }
    tag_compliance = {
      description = "Reports resources missing required tags"
      timeout     = 120
      env = {
        REQUIRED_TAGS = join(",", var.required_tags)
      }
      actions = [
        "ec2:DescribeInstances", "ec2:DescribeVolumes", "ec2:DescribeSnapshots",
        "s3:ListAllMyBuckets", "s3:GetBucketTagging", "s3:GetBucketLocation",
      ]
    }
    resource_cleanup = {
      description = "Finds and (optionally) deletes unused EBS, EIP and AMI resources"
      timeout     = 300
      env = {
        DRY_RUN             = tostring(var.cleanup_dry_run)
        VOLUME_MIN_AGE_DAYS = tostring(var.volume_min_age_days)
        AMI_MAX_AGE_DAYS    = tostring(var.ami_max_age_days)
      }
      actions = [
        "ec2:DescribeSnapshots", "ec2:DescribeVolumes", "ec2:DescribeImages", "ec2:DescribeAddresses",
        "ec2:DeleteSnapshot", "ec2:DeleteVolume", "ec2:ReleaseAddress", "ec2:DeregisterImage",
      ]
    }
    rightsizing = {
      description = "Flags under-utilised EC2 instances (recommendation only)"
      timeout     = 120
      env = {
        CPU_THRESHOLD_PERCENT = tostring(var.rightsizing_cpu_threshold)
        LOOKBACK_DAYS         = tostring(var.rightsizing_lookback_days)
      }
      actions = ["ec2:DescribeInstances", "cloudwatch:GetMetricStatistics"]
    }
  }
}

# ---- Packaging --------------------------------------------------------------
data "archive_file" "lambda" {
  for_each    = local.lambdas
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/${each.key}"
  output_path = "${path.module}/.build/${each.key}.zip"
  excludes    = ["__pycache__"]
}

# ---- IAM --------------------------------------------------------------------
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  for_each           = local.lambdas
  name               = "${var.project}-${replace(each.key, "_", "-")}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda" {
  for_each = local.lambdas

  statement {
    sid       = "TaskSpecific"
    actions   = each.value.actions
    resources = ["*"] # these read/describe APIs do not support resource-level scoping
  }

  statement {
    sid       = "WriteReports"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.reports.arn}/reports/*"]
  }

  statement {
    sid       = "Notify"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda[each.key].arn}:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  for_each = local.lambdas
  name     = "${var.project}-${replace(each.key, "_", "-")}"
  role     = aws_iam_role.lambda[each.key].id
  policy   = data.aws_iam_policy_document.lambda[each.key].json
}

# ---- Functions --------------------------------------------------------------
resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.lambdas
  name              = "/aws/lambda/${var.project}-${replace(each.key, "_", "-")}"
  retention_in_days = 14 # logs kept forever cost money
}

resource "aws_lambda_function" "this" {
  for_each = local.lambdas

  function_name    = "${var.project}-${replace(each.key, "_", "-")}"
  description      = each.value.description
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  architectures    = ["arm64"] # Graviton: ~20% cheaper per GB-second
  memory_size      = 128
  timeout          = each.value.timeout
  filename         = data.archive_file.lambda[each.key].output_path
  source_code_hash = data.archive_file.lambda[each.key].output_base64sha256

  environment {
    variables = merge(local.common_env, each.value.env)
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda]
}

# ---- Schedules --------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "schedule" {
  for_each            = local.lambdas
  name                = "${var.project}-${replace(each.key, "_", "-")}"
  schedule_expression = var.schedules[each.key]
}

resource "aws_cloudwatch_event_target" "lambda" {
  for_each = local.lambdas
  rule     = aws_cloudwatch_event_rule.schedule[each.key].name
  arn      = aws_lambda_function.this[each.key].arn
}

resource "aws_lambda_permission" "eventbridge" {
  for_each      = local.lambdas
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this[each.key].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule[each.key].arn
}
