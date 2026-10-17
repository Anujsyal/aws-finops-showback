output "reports_bucket" {
  value = aws_s3_bucket.reports.bucket
}

output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "lambda_functions" {
  value = { for k, f in aws_lambda_function.this : k => f.function_name }
}

output "team_buckets" {
  value = { for k, m in module.team : k => m.bucket }
}

output "untagged_test_volume" {
  value = try(aws_ebs_volume.untagged_test[0].id, null)
}
