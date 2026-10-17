terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.80"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
  }

  # Partial config - bucket, key, region and use_lockfile are passed with
  # -backend-config at `terraform init` (see README and the CI workflow).
  backend "s3" {}
}
