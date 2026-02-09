"""
Tests for policy presets — structure, application, rule toggling.

These tests verify:
- All presets have valid structure (constants + optional disable lists)
- Applying a preset updates constants correctly
- Applying a preset enables/disables the right rules
- Locked rules cannot be disabled by any preset
- "default" preset re-enables all rules
- "direct_full" preset disables intermediate escalation rules
- Preset round-trip: apply → read → verify matches definition
- Factory reset + policy reset produces clean state
"""

import json
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any

import pytest
import yaml

from src.cli.policy import (
    PRESETS,
    LOCKED_RULE_IDS,
    _load_rules_yaml,
    _save_rules_yaml,
    _get_rule_summary,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def policy_dir(tmp_path):
    """Create a temporary policy directory with a realistic rules.yaml."""
    src = Path(__file__).parent.parent / "policy" / "rules.yaml"
    dst = tmp_path / "policy" / "rules.yaml"
    dst.parent.mkdir(parents=True)
    shutil.copy2(src, dst)
    return tmp_path


@pytest.fixture
def rules_data(policy_dir):
    """Load rules.yaml from the fixture."""
    return _load_rules_yaml(policy_dir)


# ── Expected constant keys ────────────────────────────────────────

EXPECTED_CONSTANT_KEYS = {
    "remind_1_at_minutes",
    "remind_2_at_minutes",
    "pre_release_at_minutes",
    "partial_after_overdue_minutes",
    "full_after_overdue_minutes",
    "max_failed_attempts",
}


# ── Structure validation ─────────────────────────────────────────

class TestPresetStructure:
    """Every preset must be well-formed."""

    @pytest.mark.parametrize("name", list(PRESETS.keys()))
    def test_preset_has_constants(self, name):
        """Each preset contains a 'constants' dict."""
        preset = PRESETS[name]
        constants = preset.get("constants", {})
        assert isinstance(constants, dict), f"{name}: constants missing or not a dict"

    @pytest.mark.parametrize("name", list(PRESETS.keys()))
    def test_preset_has_all_constant_keys(self, name):
        """Each preset provides every expected constant key."""
        constants = PRESETS[name].get("constants", {})
        missing = EXPECTED_CONSTANT_KEYS - set(constants.keys())
        assert not missing, f"{name}: missing keys {missing}"

    @pytest.mark.parametrize("name", list(PRESETS.keys()))
    def test_preset_has_no_extra_keys(self, name):
        """No unexpected constant keys."""
        constants = PRESETS[name].get("constants", {})
        extra = set(constants.keys()) - EXPECTED_CONSTANT_KEYS
        assert not extra, f"{name}: unexpected keys {extra}"

    @pytest.mark.parametrize("name", list(PRESETS.keys()))
    def test_constant_values_are_nonnegative_ints(self, name):
        """All constant values must be non-negative integers."""
        constants = PRESETS[name].get("constants", {})
        for key, val in constants.items():
            assert isinstance(val, int), f"{name}.{key} = {val!r} (not int)"
            assert val >= 0, f"{name}.{key} = {val} (negative)"

    @pytest.mark.parametrize("name", list(PRESETS.keys()))
    def test_disable_list_contains_no_locked_rules(self, name):
        """No preset tries to disable a locked rule."""
        disable = set(PRESETS[name].get("disable", []))
        locked_in_disable = disable & LOCKED_RULE_IDS
        assert not locked_in_disable, \
            f"{name}: tries to disable locked rules {locked_in_disable}"

    def test_at_least_four_presets_exist(self):
        """We ship default, testing, gentle, direct_full."""
        expected = {"default", "testing", "gentle", "direct_full"}
        assert expected.issubset(set(PRESETS.keys()))


# ── Application: constants ────────────────────────────────────────

class TestPresetApplyConstants:
    """Applying a preset sets constants correctly in rules.yaml."""

    @pytest.mark.parametrize("name", list(PRESETS.keys()))
    def test_apply_sets_all_constants(self, name, policy_dir, rules_data):
        """After applying a preset, all constants match the definition."""
        preset = PRESETS[name]
        preset_constants = preset.get("constants", {})

        # Apply
        constants = rules_data.get("constants", {})
        constants.update(preset_constants)
        rules_data["constants"] = constants
        _save_rules_yaml(policy_dir, rules_data)

        # Re-read and verify
        fresh = _load_rules_yaml(policy_dir)
        for key, expected_val in preset_constants.items():
            assert fresh["constants"][key] == expected_val, \
                f"{name}: {key} expected {expected_val}, got {fresh['constants'][key]}"


# ── Application: rule toggling ────────────────────────────────────

class TestPresetApplyRules:
    """Applying a preset enables/disables the correct rules."""

    def _apply_preset(self, name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate preset application (mirrors CLI logic)."""
        preset = PRESETS[name]
        preset_constants = preset.get("constants", {})
        disable_set = set(preset.get("disable", []))

        data["constants"].update(preset_constants)

        for rule in data.get("rules", []):
            rule_id = rule.get("id", "")
            if rule_id in LOCKED_RULE_IDS:
                continue
            if rule_id in disable_set:
                rule["enabled"] = False
            else:
                rule.pop("enabled", None)  # defaults to True

        return data

    def test_default_enables_all_rules(self, rules_data):
        """'default' preset leaves all non-locked rules enabled."""
        data = self._apply_preset("default", rules_data)
        for rule in data["rules"]:
            summary = _get_rule_summary(rule)
            assert summary["enabled"] is True, \
                f"Rule {summary['id']} should be enabled after 'default'"

    def test_direct_full_disables_intermediate_rules(self, rules_data):
        """'direct_full' disables R10, R11, R12, R20."""
        expected_disabled = {
            "R10_ESCALATE_TO_REMIND_1",
            "R11_ESCALATE_TO_REMIND_2",
            "R12_ESCALATE_TO_PRE_RELEASE",
            "R20_ESCALATE_TO_PARTIAL_ON_EXPIRY",
        }

        data = self._apply_preset("direct_full", rules_data)
        for rule in data["rules"]:
            summary = _get_rule_summary(rule)
            if summary["id"] in expected_disabled:
                assert summary["enabled"] is False, \
                    f"{summary['id']} should be disabled by 'direct_full'"
            elif summary["id"] not in LOCKED_RULE_IDS:
                # R30 should remain enabled
                assert summary["enabled"] is True, \
                    f"{summary['id']} should stay enabled"

    def test_direct_full_keeps_locked_rules_enabled(self, rules_data):
        """Locked rules (R00, R01, R90) stay enabled even in direct_full."""
        data = self._apply_preset("direct_full", rules_data)
        for rule in data["rules"]:
            summary = _get_rule_summary(rule)
            if summary["locked"]:
                assert summary["enabled"] is True, \
                    f"Locked rule {summary['id']} must stay enabled"

    @pytest.mark.parametrize("name", ["testing", "gentle"])
    def test_other_presets_enable_all_rules(self, name, rules_data):
        """'testing' and 'gentle' don't disable any rules."""
        # First disable some rules to prove re-enable works
        for rule in rules_data["rules"]:
            if rule["id"] == "R10_ESCALATE_TO_REMIND_1":
                rule["enabled"] = False

        data = self._apply_preset(name, rules_data)
        for rule in data["rules"]:
            summary = _get_rule_summary(rule)
            assert summary["enabled"] is True, \
                f"Rule {summary['id']} should be re-enabled by '{name}'"


# ── Round-trip: apply → save → load → verify ─────────────────────

class TestPresetRoundTrip:
    """Apply a preset, save, reload, and verify everything matches."""

    @pytest.mark.parametrize("name", list(PRESETS.keys()))
    def test_roundtrip_constants(self, name, policy_dir, rules_data):
        """Constants survive a save/load round-trip."""
        preset = PRESETS[name]
        preset_constants = preset.get("constants", {})

        rules_data["constants"].update(preset_constants)
        _save_rules_yaml(policy_dir, rules_data)

        fresh = _load_rules_yaml(policy_dir)
        for key, expected in preset_constants.items():
            assert fresh["constants"][key] == expected

    @pytest.mark.parametrize("name", list(PRESETS.keys()))
    def test_roundtrip_rule_state(self, name, policy_dir, rules_data):
        """Rule enabled/disabled state survives a save/load round-trip."""
        preset = PRESETS[name]
        disable_set = set(preset.get("disable", []))

        # Apply
        for rule in rules_data.get("rules", []):
            rid = rule.get("id", "")
            if rid in LOCKED_RULE_IDS:
                continue
            if rid in disable_set:
                rule["enabled"] = False
            else:
                rule.pop("enabled", None)

        _save_rules_yaml(policy_dir, rules_data)

        # Reload and check
        fresh = _load_rules_yaml(policy_dir)
        for rule in fresh["rules"]:
            summary = _get_rule_summary(rule)
            rid = summary["id"]
            if rid in LOCKED_RULE_IDS:
                continue
            if rid in disable_set:
                assert summary["enabled"] is False, \
                    f"{rid} should be disabled after roundtrip"
            else:
                assert summary["enabled"] is True, \
                    f"{rid} should be enabled after roundtrip"


# ── Timing sanity checks ─────────────────────────────────────────

class TestPresetTimingSanity:
    """Verify timing makes sense for each preset."""

    def test_default_has_decreasing_reminder_windows(self):
        """Default: remind_1 > remind_2 > pre_release."""
        c = PRESETS["default"]["constants"]
        assert c["remind_1_at_minutes"] > c["remind_2_at_minutes"] > c["pre_release_at_minutes"]

    def test_testing_has_decreasing_reminder_windows(self):
        """Testing: same decreasing order but shorter."""
        c = PRESETS["testing"]["constants"]
        assert c["remind_1_at_minutes"] > c["remind_2_at_minutes"] >= c["pre_release_at_minutes"]

    def test_gentle_has_decreasing_reminder_windows(self):
        """Gentle: same pattern, much longer."""
        c = PRESETS["gentle"]["constants"]
        assert c["remind_1_at_minutes"] > c["remind_2_at_minutes"] > c["pre_release_at_minutes"]

    def test_testing_faster_than_default(self):
        """Testing preset is faster than default on every timing."""
        t = PRESETS["testing"]["constants"]
        d = PRESETS["default"]["constants"]
        assert t["remind_1_at_minutes"] < d["remind_1_at_minutes"]
        assert t["remind_2_at_minutes"] <= d["remind_2_at_minutes"]
        assert t["full_after_overdue_minutes"] < d["full_after_overdue_minutes"]

    def test_gentle_slower_than_default(self):
        """Gentle preset is slower than default on every timing."""
        g = PRESETS["gentle"]["constants"]
        d = PRESETS["default"]["constants"]
        assert g["remind_1_at_minutes"] > d["remind_1_at_minutes"]
        assert g["remind_2_at_minutes"] > d["remind_2_at_minutes"]
        assert g["full_after_overdue_minutes"] > d["full_after_overdue_minutes"]

    def test_testing_aligned_to_cron_granularity(self):
        """Testing timings should be at least 30 min (one cron tick)."""
        c = PRESETS["testing"]["constants"]
        # pre_release can be 30 (1 tick), remind_2 at least 1 tick, etc.
        assert c["pre_release_at_minutes"] >= 30, \
            "Testing pre_release should be >= 30 min (1 cron tick)"
        assert c["remind_2_at_minutes"] >= 30, \
            "Testing remind_2 should be >= 30 min"

    def test_direct_full_has_zero_timings_for_disabled_rules(self):
        """direct_full: disabled rule timings are zeroed out."""
        c = PRESETS["direct_full"]["constants"]
        assert c["remind_1_at_minutes"] == 0
        assert c["remind_2_at_minutes"] == 0
        assert c["pre_release_at_minutes"] == 0
        assert c["partial_after_overdue_minutes"] == 0
        assert c["full_after_overdue_minutes"] == 0


# ── Preset switching ─────────────────────────────────────────────

class TestPresetSwitching:
    """Switching between presets results in correct state."""

    def test_direct_full_then_default_reenables_rules(self, policy_dir, rules_data):
        """After applying direct_full, switching to default re-enables all."""
        disable_set = set(PRESETS["direct_full"].get("disable", []))

        # Apply direct_full
        for rule in rules_data["rules"]:
            rid = rule.get("id", "")
            if rid in LOCKED_RULE_IDS:
                continue
            if rid in disable_set:
                rule["enabled"] = False
            else:
                rule.pop("enabled", None)

        # Save and reload
        _save_rules_yaml(policy_dir, rules_data)
        data = _load_rules_yaml(policy_dir)

        # Verify some rules are disabled
        disabled_count = sum(
            1 for r in data["rules"]
            if r.get("enabled") is False
        )
        assert disabled_count == len(disable_set)

        # Now apply default
        for rule in data["rules"]:
            rid = rule.get("id", "")
            if rid in LOCKED_RULE_IDS:
                continue
            rule.pop("enabled", None)

        _save_rules_yaml(policy_dir, data)
        fresh = _load_rules_yaml(policy_dir)

        # All should be enabled now
        for rule in fresh["rules"]:
            summary = _get_rule_summary(rule)
            assert summary["enabled"] is True, \
                f"{summary['id']} should be re-enabled after switching to 'default'"

    def test_all_presets_applied_sequentially(self, policy_dir, rules_data):
        """Apply every preset in sequence — final state matches the last one."""
        for name in ["testing", "direct_full", "gentle", "default"]:
            preset = PRESETS[name]
            rules_data["constants"].update(preset.get("constants", {}))
            disable_set = set(preset.get("disable", []))
            for rule in rules_data["rules"]:
                rid = rule.get("id", "")
                if rid in LOCKED_RULE_IDS:
                    continue
                if rid in disable_set:
                    rule["enabled"] = False
                else:
                    rule.pop("enabled", None)

        # Final state should match "default"
        _save_rules_yaml(policy_dir, rules_data)
        fresh = _load_rules_yaml(policy_dir)

        default_constants = PRESETS["default"]["constants"]
        for key, expected in default_constants.items():
            assert fresh["constants"][key] == expected, \
                f"After sequential apply, {key} should be {expected}"

        for rule in fresh["rules"]:
            summary = _get_rule_summary(rule)
            assert summary["enabled"] is True, \
                f"After sequential apply ending with 'default', {summary['id']} should be enabled"


# ── Factory reset backup includes policy ─────────────────────────

class TestFactoryResetBackupPolicy:
    """The automatic backup during factory reset must include policy."""

    def test_backup_archive_includes_policy_files(self, tmp_path):
        """create_backup_archive with include_policy=True archives policy/."""
        from src.cli.backup import create_backup_archive, read_archive_manifest
        import tarfile

        # Set up minimal project structure
        (tmp_path / "state").mkdir()
        state_file = tmp_path / "state" / "current.json"
        state_file.write_text('{"meta": {"schema_version": 1}}')
        (tmp_path / "audit").mkdir()
        (tmp_path / "audit" / "ledger.ndjson").write_text("")

        # Copy real policy files
        src_policy = Path(__file__).parent.parent / "policy"
        dst_policy = tmp_path / "policy"
        shutil.copytree(src_policy, dst_policy)

        # Create backup WITH policy
        import os
        os.environ.setdefault("PROJECT_NAME", "test-project")
        archive_path, manifest = create_backup_archive(
            tmp_path,
            include_state=True,
            include_audit=True,
            include_policy=True,
            trigger="factory_reset",
        )

        # Verify manifest says policy is included
        assert manifest["includes"]["policy"] is True

        # Verify archive actually contains policy files
        with tarfile.open(archive_path, "r:gz") as tar:
            policy_files = [m.name for m in tar.getmembers()
                           if m.name.startswith("policy/")]
            assert len(policy_files) > 0, "Archive should contain policy/ files"
            assert any("rules.yaml" in f for f in policy_files), \
                "Archive should contain policy/rules.yaml"

    def test_backup_without_policy_flag_excludes_policy(self, tmp_path):
        """create_backup_archive without include_policy does NOT archive policy/."""
        from src.cli.backup import create_backup_archive
        import tarfile

        (tmp_path / "state").mkdir()
        (tmp_path / "state" / "current.json").write_text('{"meta": {}}')
        (tmp_path / "audit").mkdir()
        (tmp_path / "audit" / "ledger.ndjson").write_text("")
        src_policy = Path(__file__).parent.parent / "policy"
        shutil.copytree(src_policy, tmp_path / "policy")

        import os
        os.environ.setdefault("PROJECT_NAME", "test-project")
        archive_path, manifest = create_backup_archive(
            tmp_path,
            include_state=True,
            include_audit=True,
            include_policy=False,
            trigger="test",
        )

        assert manifest["includes"]["policy"] is False
        with tarfile.open(archive_path, "r:gz") as tar:
            policy_files = [m.name for m in tar.getmembers()
                           if m.name.startswith("policy/")]
            assert len(policy_files) == 0, \
                "Archive should NOT contain policy/ when include_policy=False"

    def test_restore_policy_from_archive(self, tmp_path):
        """Policy files are correctly restored from an archive."""
        from src.cli.backup import create_backup_archive, restore_from_archive

        # Create source project with policy
        src_root = tmp_path / "src_project"
        src_root.mkdir()
        (src_root / "state").mkdir()
        (src_root / "state" / "current.json").write_text('{"meta": {}}')
        (src_root / "audit").mkdir()
        (src_root / "audit" / "ledger.ndjson").write_text("")
        src_policy = Path(__file__).parent.parent / "policy"
        shutil.copytree(src_policy, src_root / "policy")

        # Modify a constant to prove restore works
        rules_data = _load_rules_yaml(src_root)
        rules_data["constants"]["remind_1_at_minutes"] = 9999
        _save_rules_yaml(src_root, rules_data)

        # Create backup
        import os
        os.environ.setdefault("PROJECT_NAME", "test-project")
        archive_path, _ = create_backup_archive(
            src_root, include_state=True, include_policy=True,
            trigger="test",
        )

        # Create a destination project with different policy
        dst_root = tmp_path / "dst_project"
        dst_root.mkdir()
        shutil.copytree(src_policy, dst_root / "policy")
        original = _load_rules_yaml(dst_root)
        assert original["constants"]["remind_1_at_minutes"] != 9999

        # Restore
        result = restore_from_archive(
            dst_root, archive_path, restore_policy=True,
        )

        # Verify the modified constant was restored
        restored = _load_rules_yaml(dst_root)
        assert restored["constants"]["remind_1_at_minutes"] == 9999, \
            "Policy restore should have overwritten rules.yaml"
        assert any("policy/rules.yaml" in f for f in result["restored"]), \
            "rules.yaml should be in restored file list"

