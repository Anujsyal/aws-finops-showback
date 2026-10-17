# One "team" worth of demo resources, all tagged with the team's name so
# their cost can be charged back. Tiny sizes keep the cost near zero.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

variable "team" {
  type = string
}

variable "owner" {
  type = string
}

variable "project" {
  type = string
}

variable "account_id" {
  type = string
}

variable "ec2_enabled" {
  type    = bool
  default = false
}

locals {
  # Overrides the provider's default Team/Owner tags.
  tags = {
    Team  = var.team
    Owner = var.owner
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

# ---- S3 bucket --------------------------------------------------------------
resource "aws_s3_bucket" "data" {
  bucket        = "${var.project}-${var.team}-${var.account_id}"
  force_destroy = true
  tags          = local.tags
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---- EBS volume + snapshot (1 GiB = a few rupees a month) ------------------
resource "aws_ebs_volume" "data" {
  availability_zone = data.aws_availability_zones.available.names[0]
  size              = 1
  type              = "gp3"
  encrypted         = true
  tags              = merge(local.tags, { Name = "${var.team}-data" })
}

resource "aws_ebs_snapshot" "data" {
  volume_id = aws_ebs_volume.data.id
  tags      = merge(local.tags, { Name = "${var.team}-data-snapshot" })
}

# ---- Optional EC2 instance (for rightsizing tests) -------------------------
data "aws_ssm_parameter" "al2023" {
  count = var.ec2_enabled ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "app" {
  count         = var.ec2_enabled ? 1 : 0
  ami           = data.aws_ssm_parameter.al2023[0].value
  instance_type = "t3.micro"

  # No public IP: avoids the public IPv4 charge. We only need CPU metrics.
  associate_public_ip_address = false

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
    encrypted   = true
    tags        = local.tags
  }

  tags = merge(local.tags, { Name = "${var.team}-app" })
}

output "bucket" {
  value = aws_s3_bucket.data.bucket
}

output "instance_id" {
  value = try(aws_instance.app[0].id, null)
}
