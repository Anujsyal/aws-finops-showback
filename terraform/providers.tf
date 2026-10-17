provider "aws" {
  region = var.aws_region

  # Every resource gets these tags automatically. Team defaults to the
  # platform team; the per-team module overrides it with its own team name.
  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      Owner       = var.owner
      Team        = "platform-finops"
      ManagedBy   = "terraform"
    }
  }
}

# A provider WITHOUT default tags, used only to create one deliberately
# untagged resource so the tag-compliance Lambda has something to catch.
provider "aws" {
  alias  = "untagged"
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
