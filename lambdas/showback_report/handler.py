"""Showback report Lambda.

Pulls the last N days of AWS spend from Cost Explorer, grouped by the `Team`
cost allocation tag, saves a CSV to S3 and sends a per-team summary via SNS.

Cost note: every Cost Explorer API request costs $0.01, so this function makes
exactly ONE request per run (pagination aside). Run it weekly, not hourly.
"""

import csv
import io
import json
import logging
import os
from datetime import UTC, datetime, timedelta

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

UNTAGGED_LABEL = "(untagged)"

# Showback reports what teams used, not what the bill came to after credits,
# so promotional credits and refunds are left out.
EXCLUDED_RECORD_TYPES = ["Credit", "Refund"]


def parse_team_costs(results_by_time, tag_key="Team"):
    """Sum Cost Explorer results per team.

    Cost Explorer returns group keys like "Team$team-payments", and "Team$"
    for spend that has no Team tag. Returns {team: total_usd}.
    """
    totals = {}
    prefix = f"{tag_key}$"
    for period in results_by_time:
        for group in period.get("Groups", []):
            raw_key = group["Keys"][0]
            team = raw_key.removeprefix(prefix)
            team = team or UNTAGGED_LABEL
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            totals[team] = totals.get(team, 0.0) + amount
    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def build_csv(totals, start, end):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["period_start", "period_end", "team", "cost_usd"])
    for team, cost in totals.items():
        writer.writerow([start, end, team, f"{cost:.4f}"])
    return buf.getvalue()


def build_summary(totals, start, end):
    grand_total = sum(totals.values())
    lines = [f"AWS Showback Report ({start} to {end})", ""]
    for team, cost in totals.items():
        share = (cost / grand_total * 100) if grand_total else 0
        lines.append(f"  {team:<20} ${cost:>10.4f}  ({share:5.1f}%)")
    lines += ["", f"  {'TOTAL':<20} ${grand_total:>10.4f}"]
    if UNTAGGED_LABEL in totals:
        lines += ["", "Note: untagged spend cannot be charged back. Fix tags to improve coverage."]
    return "\n".join(lines)


def get_costs(ce, start, end, tag_key):
    results, token = [], None
    while True:
        kwargs = {
            "TimePeriod": {"Start": start, "End": end},
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [{"Type": "TAG", "Key": tag_key}],
            "Filter": {"Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": EXCLUDED_RECORD_TYPES}}},
        }
        if token:
            kwargs["NextPageToken"] = token
        resp = ce.get_cost_and_usage(**kwargs)
        results.extend(resp["ResultsByTime"])
        token = resp.get("NextPageToken")
        if not token:
            return results


def lambda_handler(event, context):
    bucket = os.environ["REPORT_BUCKET"]
    topic_arn = os.environ["SNS_TOPIC_ARN"]
    tag_key = os.environ.get("COST_TAG_KEY", "Team")
    lookback = int(os.environ.get("LOOKBACK_DAYS", "7"))

    end = datetime.now(UTC).date()
    start = end - timedelta(days=lookback)
    start_s, end_s = start.isoformat(), end.isoformat()  # End is exclusive in CE

    # Cost Explorer is a global service served from us-east-1.
    ce = boto3.client("ce", region_name="us-east-1")
    totals = parse_team_costs(get_costs(ce, start_s, end_s, tag_key), tag_key)

    key = f"reports/showback/{end_s}.csv"
    boto3.client("s3").put_object(
        Bucket=bucket, Key=key, Body=build_csv(totals, start_s, end_s).encode(),
        ContentType="text/csv",
    )

    summary = build_summary(totals, start_s, end_s)
    boto3.client("sns").publish(
        TopicArn=topic_arn, Subject=f"AWS Showback Report {end_s}", Message=summary,
    )
    logger.info(summary)
    return {"report": f"s3://{bucket}/{key}", "teams": totals}


if __name__ == "__main__":  # local smoke test: python handler.py
    print(json.dumps(lambda_handler({}, None), indent=2))
