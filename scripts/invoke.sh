#!/usr/bin/env bash
# Run a Lambda now instead of waiting for its schedule.
# Usage: ./scripts/invoke.sh showback-report | tag-compliance | resource-cleanup | rightsizing
set -euo pipefail
NAME="finops-showback-${1:?pass a lambda name, e.g. tag-compliance}"
aws lambda invoke --region "${AWS_REGION:-ap-south-1}" --function-name "$NAME" \
  --cli-binary-format raw-in-base64-out --payload '{}' /dev/stdout
echo
