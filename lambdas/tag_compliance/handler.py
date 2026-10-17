"""Tag compliance Lambda.

Finds EC2 instances, EBS volumes, EBS snapshots and S3 buckets that are missing
any of the required tags, writes a JSON report to S3 and alerts via SNS.

Why not only the Resource Groups Tagging API? It only returns resources that
have (or once had) tags, so a resource that was NEVER tagged is invisible to it.
Querying each service directly catches those.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def tags_to_dict(tag_list):
    return {t["Key"]: t["Value"] for t in (tag_list or [])}


def missing_tags(tags, required):
    """Return required tag keys that are absent or have an empty value."""
    return [k for k in required if not str(tags.get(k, "")).strip()]


def scan_ec2(ec2, required):
    findings = []
    for page in ec2.get_paginator("describe_instances").paginate():
        for res in page["Reservations"]:
            for inst in res["Instances"]:
                if inst["State"]["Name"] == "terminated":
                    continue
                miss = missing_tags(tags_to_dict(inst.get("Tags")), required)
                if miss:
                    findings.append({"type": "ec2:instance", "id": inst["InstanceId"], "missing": miss})
    return findings


def scan_volumes(ec2, required):
    findings = []
    for page in ec2.get_paginator("describe_volumes").paginate():
        for vol in page["Volumes"]:
            miss = missing_tags(tags_to_dict(vol.get("Tags")), required)
            if miss:
                findings.append({"type": "ec2:volume", "id": vol["VolumeId"], "missing": miss})
    return findings


def scan_snapshots(ec2, required):
    findings = []
    for page in ec2.get_paginator("describe_snapshots").paginate(OwnerIds=["self"]):
        for snap in page["Snapshots"]:
            miss = missing_tags(tags_to_dict(snap.get("Tags")), required)
            if miss:
                findings.append({"type": "ec2:snapshot", "id": snap["SnapshotId"], "missing": miss})
    return findings


def scan_buckets(s3, required, region):
    findings = []
    for bucket in s3.list_buckets()["Buckets"]:
        name = bucket["Name"]
        try:
            loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
            if loc != region:
                continue  # only report buckets in this Lambda's region
            tags = tags_to_dict(s3.get_bucket_tagging(Bucket=name)["TagSet"])
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchTagSet":
                tags = {}
            else:
                logger.warning("Skipping bucket %s: %s", name, err)
                continue
        miss = missing_tags(tags, required)
        if miss:
            findings.append({"type": "s3:bucket", "id": name, "missing": miss})
    return findings


def lambda_handler(event, context):
    required = [t.strip() for t in os.environ.get("REQUIRED_TAGS", "Team").split(",") if t.strip()]
    bucket = os.environ["REPORT_BUCKET"]
    topic_arn = os.environ["SNS_TOPIC_ARN"]
    region = os.environ.get("AWS_REGION", "ap-south-1")

    ec2, s3 = boto3.client("ec2"), boto3.client("s3")
    findings = (
        scan_ec2(ec2, required) + scan_volumes(ec2, required)
        + scan_snapshots(ec2, required) + scan_buckets(s3, required, region)
    )

    today = datetime.now(timezone.utc).date().isoformat()
    key = f"reports/tag-compliance/{today}.json"
    report = {"date": today, "required_tags": required, "non_compliant": findings}
    boto3.client("s3").put_object(
        Bucket=bucket, Key=key, Body=json.dumps(report, indent=2).encode(),
        ContentType="application/json",
    )

    if findings:
        lines = [f"{len(findings)} resource(s) missing required tags {required}:", ""]
        lines += [f"  {f['type']:<14} {f['id']:<40} missing: {', '.join(f['missing'])}" for f in findings[:50]]
        if len(findings) > 50:
            lines.append(f"  ...and {len(findings) - 50} more. Full report: s3://{bucket}/{key}")
        boto3.client("sns").publish(
            TopicArn=topic_arn, Subject=f"Tag compliance: {len(findings)} issue(s)", Message="\n".join(lines),
        )
    logger.info("Found %d non-compliant resources", len(findings))
    return {"non_compliant": len(findings), "report": f"s3://{bucket}/{key}"}
