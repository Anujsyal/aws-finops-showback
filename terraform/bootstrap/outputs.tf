output "state_bucket" {
  description = "Put this in GitHub as the TF_STATE_BUCKET variable."
  value       = aws_s3_bucket.tfstate.bucket
}

output "github_actions_role_arn" {
  description = "Put this in GitHub as the AWS_ROLE_ARN variable."
  value       = aws_iam_role.github_actions.arn
}
