# Fake teams whose spend we charge back.
module "team" {
  source   = "./modules/team"
  for_each = var.teams

  team        = each.key
  owner       = each.value.owner
  project     = var.project
  account_id  = data.aws_caller_identity.current.account_id
  ec2_enabled = var.demo_ec2_enabled
}

# Deliberately UNTAGGED volume - the tag-compliance Lambda should flag it.
data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_ebs_volume" "untagged_test" {
  count    = var.create_untagged_test_resource ? 1 : 0
  provider = aws.untagged

  availability_zone = data.aws_availability_zones.available.names[0]
  size              = 1
  type              = "gp3"
  encrypted         = true
}
