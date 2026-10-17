"""Rightsizing recommendations Lambda.

Reads the average CPUUtilization of every running EC2 instance over the last N
days and flags instances below a threshold with a suggested smaller type.

This is RECOMMENDATION ONLY. Resizing needs a stop/start and can break
workloads, so a human decides. That's a deliberate design choice.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SIZE_ORDER = ["nano", "micro", "small", "medium", "large", "xlarge", "2xlarge",
              "4xlarge", "8xlarge", "12xlarge", "16xlarge", "24xlarge"]


def suggest_smaller_type(instance_type):
    """t3.large -> t3.medium. Returns None when already the smallest size."""
    family, _, size = instance_type.partition(".")
    if size not in SIZE_ORDER:
        return None
    idx = SIZE_ORDER.index(size)
    return f"{family}.{SIZE_ORDER[idx - 1]}" if idx > 0 else None


def average(datapoints):
    values = [d["Average"] for d in datapoints]
    return sum(values) / len(values) if values else None


def evaluate(instance, avg_cpu, threshold):
    """Return a recommendation dict, or None if the instance is fine."""
    if avg_cpu is None or avg_cpu >= threshold:
        return None
    tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
    return {
        "instance_id": instance["InstanceId"],
        "team": tags.get("Team", "(untagged)"),
        "current_type": instance["InstanceType"],
        "suggested_type": suggest_smaller_type(instance["InstanceType"]) or "consider stopping/scheduling",
        "avg_cpu_percent": round(avg_cpu, 2),
    }


def lambda_handler(event, context):
    threshold = float(os.environ.get("CPU_THRESHOLD_PERCENT", "10"))
    lookback = int(os.environ.get("LOOKBACK_DAYS", "14"))
    bucket = os.environ["REPORT_BUCKET"]
    topic_arn = os.environ["SNS_TOPIC_ARN"]

    ec2, cw = boto3.client("ec2"), boto3.client("cloudwatch")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback)

    recs = []
    pages = ec2.get_paginator("describe_instances").paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
    for page in pages:
        for res in page["Reservations"]:
            for inst in res["Instances"]:
                stats = cw.get_metric_statistics(
                    Namespace="AWS/EC2", MetricName="CPUUtilization",
                    Dimensions=[{"Name": "InstanceId", "Value": inst["InstanceId"]}],
                    StartTime=start, EndTime=end, Period=86400, Statistics=["Average"],
                )
                rec = evaluate(inst, average(stats["Datapoints"]), threshold)
                if rec:
                    recs.append(rec)

    today = datetime.now(timezone.utc).date().isoformat()
    key = f"reports/rightsizing/{today}.json"
    report = {"date": today, "threshold_percent": threshold, "lookback_days": lookback, "recommendations": recs}
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=json.dumps(report, indent=2).encode(),
                                  ContentType="application/json")

    if recs:
        lines = [f"{len(recs)} under-utilised instance(s) (avg CPU < {threshold}% over {lookback} days):", ""]
        lines += [f"  {r['instance_id']}  {r['team']:<16} {r['current_type']:>10} -> {r['suggested_type']:<12}"
                  f" avg CPU {r['avg_cpu_percent']}%" for r in recs]
        boto3.client("sns").publish(TopicArn=topic_arn, Subject="EC2 rightsizing recommendations",
                                    Message="\n".join(lines))
    logger.info(json.dumps(report))
    return {"recommendations": len(recs), "report": f"s3://{bucket}/{key}"}
