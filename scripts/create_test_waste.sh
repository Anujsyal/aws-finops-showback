#!/usr/bin/env bash
# Creates "waste" for the cleanup Lambda to find:
#   1. an orphan snapshot (its source volume is deleted)
#   2. an unattached EBS volume
# Everything is 1 GiB, so it costs almost nothing. Run the cleanup Lambda
# afterwards (dry-run first!) and check the report.
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
AZ="$(aws ec2 describe-availability-zones --region "$REGION" --query 'AvailabilityZones[0].ZoneName' --output text)"
TAGS='ResourceType=volume,Tags=[{Key=Team,Value=team-search},{Key=Environment,Value=dev},{Key=Project,Value=finops-showback},{Key=Owner,Value=rahul}]'

echo "Creating a volume that will become an orphan snapshot's source..."
VOL=$(aws ec2 create-volume --region "$REGION" --availability-zone "$AZ" --size 1 --volume-type gp3 \
  --tag-specifications "$TAGS" --query VolumeId --output text)
aws ec2 wait volume-available --region "$REGION" --volume-ids "$VOL"

SNAP=$(aws ec2 create-snapshot --region "$REGION" --volume-id "$VOL" --description "orphan test" \
  --tag-specifications 'ResourceType=snapshot,Tags=[{Key=Team,Value=team-search}]' --query SnapshotId --output text)
aws ec2 wait snapshot-completed --region "$REGION" --snapshot-ids "$SNAP"
aws ec2 delete-volume --region "$REGION" --volume-id "$VOL"
echo "Orphan snapshot: $SNAP (source volume $VOL deleted)"

echo "Creating an unattached volume..."
UNATTACHED=$(aws ec2 create-volume --region "$REGION" --availability-zone "$AZ" --size 1 --volume-type gp3 \
  --tag-specifications "$TAGS" --query VolumeId --output text)
echo "Unattached volume: $UNATTACHED"
echo
echo "Note: the cleanup Lambda only flags unattached volumes older than VOLUME_MIN_AGE_DAYS (default 7)."
echo "To test right away: set volume_min_age_days = 0 in terraform.tfvars and apply."
