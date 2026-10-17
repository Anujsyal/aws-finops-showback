"""Resource cleanup Lambda.

Finds (and optionally deletes) waste:
  * EBS snapshots whose source volume no longer exists and are not used by any AMI
  * Unattached EBS volumes older than N days
  * Elastic IPs not associated with anything (charged hourly)
  * Self-owned AMIs older than N days (deregistered together with their snapshots)

Safety:
  * DRY_RUN=true (the default) only reports; nothing is deleted.
  * Any resource tagged Keep=true is always skipped.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def is_protected(tag_list, keep_key="Keep"):
    return any(t["Key"] == keep_key and t["Value"].lower() == "true" for t in (tag_list or []))


def older_than(ts, days, now=None):
    now = now or datetime.now(timezone.utc)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return ts < now - timedelta(days=days)


def find_orphan_snapshots(snapshots, existing_volume_ids, ami_snapshot_ids):
    """Snapshots whose source volume is gone and that no AMI depends on."""
    return [
        s for s in snapshots
        if s.get("VolumeId") not in existing_volume_ids
        and s["SnapshotId"] not in ami_snapshot_ids
        and not is_protected(s.get("Tags"))
    ]


def find_unattached_volumes(volumes, min_age_days, now=None):
    return [
        v for v in volumes
        if v["State"] == "available"
        and older_than(v["CreateTime"], min_age_days, now)
        and not is_protected(v.get("Tags"))
    ]


def find_idle_eips(addresses):
    return [
        a for a in addresses
        if not a.get("AssociationId") and not is_protected(a.get("Tags"))
    ]


def find_old_amis(images, max_age_days, now=None):
    return [
        i for i in images
        if older_than(i["CreationDate"], max_age_days, now) and not is_protected(i.get("Tags"))
    ]


def ami_snapshot_ids(image):
    return [bdm["Ebs"]["SnapshotId"] for bdm in image.get("BlockDeviceMappings", [])
            if "Ebs" in bdm and "SnapshotId" in bdm["Ebs"]]


def _paginate(ec2, op, key, **kwargs):
    items = []
    for page in ec2.get_paginator(op).paginate(**kwargs):
        items.extend(page[key])
    return items


def lambda_handler(event, context):
    dry_run = os.environ.get("DRY_RUN", "true").lower() != "false"
    volume_age = int(os.environ.get("VOLUME_MIN_AGE_DAYS", "7"))
    ami_age = int(os.environ.get("AMI_MAX_AGE_DAYS", "90"))
    bucket = os.environ["REPORT_BUCKET"]
    topic_arn = os.environ["SNS_TOPIC_ARN"]

    ec2 = boto3.client("ec2")
    snapshots = _paginate(ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"])
    volumes = _paginate(ec2, "describe_volumes", "Volumes")
    images = ec2.describe_images(Owners=["self"])["Images"]
    addresses = ec2.describe_addresses()["Addresses"]

    volume_ids = {v["VolumeId"] for v in volumes}
    old_amis = find_old_amis(images, ami_age)
    old_ami_ids = {i["ImageId"] for i in old_amis}
    # Snapshots of AMIs we are keeping must not be touched.
    kept_ami_snaps = {sid for i in images if i["ImageId"] not in old_ami_ids for sid in ami_snapshot_ids(i)}
    all_ami_snaps = {sid for i in images for sid in ami_snapshot_ids(i)}

    plan = {
        "snapshots": [s["SnapshotId"] for s in find_orphan_snapshots(snapshots, volume_ids, all_ami_snaps)],
        "volumes": [v["VolumeId"] for v in find_unattached_volumes(volumes, volume_age)],
        "elastic_ips": [a["AllocationId"] for a in find_idle_eips(addresses) if "AllocationId" in a],
        "amis": [{"ImageId": i["ImageId"], "snapshots": [s for s in ami_snapshot_ids(i) if s not in kept_ami_snaps]}
                 for i in old_amis],
    }

    actions, errors = [], []

    def act(desc, fn, **kwargs):
        if dry_run:
            actions.append(f"[DRY-RUN] would {desc}")
            return
        try:
            fn(**kwargs)
            actions.append(f"{desc}: done")
        except ClientError as err:
            errors.append(f"{desc}: {err.response['Error']['Code']}")

    for ami in plan["amis"]:
        act(f"deregister AMI {ami['ImageId']}", ec2.deregister_image, ImageId=ami["ImageId"])
        for sid in ami["snapshots"]:
            act(f"delete AMI snapshot {sid}", ec2.delete_snapshot, SnapshotId=sid)
    for sid in plan["snapshots"]:
        act(f"delete snapshot {sid}", ec2.delete_snapshot, SnapshotId=sid)
    for vid in plan["volumes"]:
        act(f"delete volume {vid}", ec2.delete_volume, VolumeId=vid)
    for aid in plan["elastic_ips"]:
        act(f"release Elastic IP {aid}", ec2.release_address, AllocationId=aid)

    today = datetime.now(timezone.utc).date().isoformat()
    key = f"reports/cleanup/{today}.json"
    report = {"date": today, "dry_run": dry_run, "plan": plan, "actions": actions, "errors": errors}
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=json.dumps(report, indent=2).encode(),
                                  ContentType="application/json")

    if actions or errors:
        mode = "DRY-RUN" if dry_run else "LIVE"
        msg = [f"Resource cleanup ({mode}) - {len(actions)} action(s), {len(errors)} error(s)", ""]
        msg += actions[:60] + ([""] + ["Errors:"] + errors if errors else [])
        msg += ["", f"Full report: s3://{bucket}/{key}"]
        boto3.client("sns").publish(TopicArn=topic_arn, Subject=f"AWS cleanup report ({mode})",
                                    Message="\n".join(msg))
    logger.info(json.dumps(report))
    return {"dry_run": dry_run, "actions": len(actions), "errors": len(errors)}
