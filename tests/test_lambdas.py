"""Unit tests for the pure logic in each Lambda (no AWS calls needed)."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "lambdas"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / name / "handler.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


showback = load("showback_report")
tags = load("tag_compliance")
cleanup = load("resource_cleanup")
rightsizing = load("rightsizing")

NOW = datetime(2026, 10, 17, tzinfo=UTC)


# ---- showback_report -------------------------------------------------------
def test_parse_team_costs_sums_days_and_labels_untagged():
    results = [
        {"Groups": [
            {"Keys": ["Team$team-payments"], "Metrics": {"UnblendedCost": {"Amount": "1.5"}}},
            {"Keys": ["Team$"], "Metrics": {"UnblendedCost": {"Amount": "0.25"}}},
        ]},
        {"Groups": [
            {"Keys": ["Team$team-payments"], "Metrics": {"UnblendedCost": {"Amount": "0.5"}}},
            {"Keys": ["Team$team-search"], "Metrics": {"UnblendedCost": {"Amount": "1"}}},
        ]},
    ]
    totals = showback.parse_team_costs(results)
    assert totals == {"team-payments": 2.0, "team-search": 1.0, "(untagged)": 0.25}
    assert next(iter(totals)) == "team-payments"  # sorted by cost desc


def test_summary_mentions_untagged_spend():
    summary = showback.build_summary({"team-a": 1.0, "(untagged)": 1.0}, "2026-10-10", "2026-10-17")
    assert "TOTAL" in summary and "untagged spend" in summary


def test_get_costs_excludes_credits_and_refunds():
    class FakeCE:
        def get_cost_and_usage(self, **kwargs):
            self.kwargs = kwargs
            return {"ResultsByTime": []}

    ce = FakeCE()
    showback.get_costs(ce, "2026-10-12", "2026-10-19", "Team")
    excluded = ce.kwargs["Filter"]["Not"]["Dimensions"]
    assert excluded["Key"] == "RECORD_TYPE" and {"Credit", "Refund"} <= set(excluded["Values"])


# ---- tag_compliance --------------------------------------------------------
def test_missing_tags_treats_blank_values_as_missing():
    assert tags.missing_tags({"Team": "x", "Owner": " "}, ["Team", "Owner", "Project"]) == ["Owner", "Project"]


# ---- resource_cleanup ------------------------------------------------------
def test_orphan_snapshots_skip_existing_volumes_amis_and_keep_tag():
    snaps = [
        {"SnapshotId": "snap-orphan", "VolumeId": "vol-gone"},
        {"SnapshotId": "snap-live", "VolumeId": "vol-1"},
        {"SnapshotId": "snap-ami", "VolumeId": "vol-gone"},
        {"SnapshotId": "snap-keep", "VolumeId": "vol-gone", "Tags": [{"Key": "Keep", "Value": "true"}]},
    ]
    result = cleanup.find_orphan_snapshots(snaps, {"vol-1"}, {"snap-ami"})
    assert [s["SnapshotId"] for s in result] == ["snap-orphan"]


def test_unattached_volumes_respect_min_age():
    vols = [
        {"VolumeId": "vol-old", "State": "available", "CreateTime": NOW - timedelta(days=30)},
        {"VolumeId": "vol-new", "State": "available", "CreateTime": NOW - timedelta(days=1)},
        {"VolumeId": "vol-used", "State": "in-use", "CreateTime": NOW - timedelta(days=30)},
    ]
    result = cleanup.find_unattached_volumes(vols, 7, now=NOW)
    assert [v["VolumeId"] for v in result] == ["vol-old"]


def test_idle_eips_and_old_amis():
    eips = [{"AllocationId": "a1"}, {"AllocationId": "a2", "AssociationId": "x"}]
    assert [a["AllocationId"] for a in cleanup.find_idle_eips(eips)] == ["a1"]
    images = [
        {"ImageId": "ami-old", "CreationDate": "2026-01-01T00:00:00.000Z"},
        {"ImageId": "ami-new", "CreationDate": "2026-10-10T00:00:00.000Z"},
    ]
    assert [i["ImageId"] for i in cleanup.find_old_amis(images, 90, now=NOW)] == ["ami-old"]


# ---- rightsizing -----------------------------------------------------------
def test_suggest_smaller_type():
    assert rightsizing.suggest_smaller_type("t3.large") == "t3.medium"
    assert rightsizing.suggest_smaller_type("m5.2xlarge") == "m5.xlarge"
    assert rightsizing.suggest_smaller_type("t3.nano") is None


def test_evaluate_flags_only_low_cpu():
    inst = {"InstanceId": "i-1", "InstanceType": "t3.small", "Tags": [{"Key": "Team", "Value": "team-search"}]}
    rec = rightsizing.evaluate(inst, 3.2, 10)
    assert rec["suggested_type"] == "t3.micro" and rec["team"] == "team-search"
    assert rightsizing.evaluate(inst, 45.0, 10) is None
    assert rightsizing.evaluate(inst, None, 10) is None
