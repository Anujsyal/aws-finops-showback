variable "aws_region" {
  description = "AWS region for the state bucket and IAM resources."
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Project name, used as a prefix for every resource."
  type        = string
  default     = "finops-showback"
}

variable "owner" {
  description = "Value for the Owner tag."
  type        = string
  default     = "anuj"
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy, in owner/name form."
  type        = string
  default     = "Anujsyal/aws-finops-showback"
}
