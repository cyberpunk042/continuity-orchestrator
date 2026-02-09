"""
CLI policy commands — read and update policy/rules.yaml constants and rule toggles.

Usage:
    python -m src.main policy-constants                          # show current
    python -m src.main policy-constants --json                   # machine output
    python -m src.main policy-constants --set KEY=VALUE          # update constant
    python -m src.main policy-constants --enable RULE_ID         # enable rule
    python -m src.main policy-constants --disable RULE_ID        # disable rule
    python -m src.main policy-constants --preset testing         # apply preset
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
import yaml


# ── Locked rules (cannot be disabled — system integrity) ──────────

LOCKED_RULE_IDS = frozenset({
    "R00_RENEWAL_SUCCESS_RESETS",
    "R01_LOCKOUT_ON_MAX_FAILED_ATTEMPTS",
    "R90_ENFORCE_MONOTONIC",
})


# ── Presets ───────────────────────────────────────────────────────
# Each preset has:
#   constants:  timing values to set
#   disable:    list of rule IDs to disable (omitted → enable all non-locked)
#                                                                   
# Timing note: GitHub Actions cron runs at ~30 min granularity.
# "Testing" preset aligns to 1-2 cron cycles.  The engine fires
# each rule when the next tick crosses the threshold, so values
# smaller than the cron interval still work — they just fire on
# the first tick after the window opens.

PRESETS: Dict[str, Dict] = {
    "default": {
        "constants": {
            "remind_1_at_minutes": 360,       # 6 h
            "remind_2_at_minutes": 60,        # 1 h
            "pre_release_at_minutes": 15,     # 15 min
            "partial_after_overdue_minutes": 0,
            "full_after_overdue_minutes": 120, # 2 h
            "max_failed_attempts": 3,
        },
        # all rules enabled (no disable list)
    },
    "testing": {
        "constants": {
            "remind_1_at_minutes": 90,        # ~3 cron ticks before deadline
            "remind_2_at_minutes": 60,        # ~2 ticks
            "pre_release_at_minutes": 30,     # ~1 tick
            "partial_after_overdue_minutes": 0,
            "full_after_overdue_minutes": 30,  # ~1 tick after partial
            "max_failed_attempts": 3,
        },
    },
    "direct_full": {
        "constants": {
            "remind_1_at_minutes": 0,
            "remind_2_at_minutes": 0,
            "pre_release_at_minutes": 0,
            "partial_after_overdue_minutes": 0,
            "full_after_overdue_minutes": 0,
            "max_failed_attempts": 3,
        },
        "disable": [
            "R10_ESCALATE_TO_REMIND_1",
            "R11_ESCALATE_TO_REMIND_2",
            "R12_ESCALATE_TO_PRE_RELEASE",
            "R20_ESCALATE_TO_PARTIAL_ON_EXPIRY",
        ],
    },
    "gentle": {
        "constants": {
            "remind_1_at_minutes": 1440,      # 24 h
            "remind_2_at_minutes": 360,       # 6 h
            "pre_release_at_minutes": 60,     # 1 h
            "partial_after_overdue_minutes": 60,  # 1 h delay
            "full_after_overdue_minutes": 360, # 6 h after overdue
            "max_failed_attempts": 5,
        },
    },
}


# ── YAML helpers ──────────────────────────────────────────────────

def _load_rules_yaml(root: Path) -> Dict[str, Any]:
    """Load and parse policy/rules.yaml."""
    path = root / "policy" / "rules.yaml"
    if not path.exists():
        raise click.ClickException(f"Rules file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_rules_yaml(root: Path, data: Dict[str, Any]) -> None:
    """Write policy/rules.yaml back, preserving structure."""
    path = root / "policy" / "rules.yaml"

    # Custom representer to keep multi-line strings readable
    class _Dumper(yaml.SafeDumper):
        pass

    def _str_representer(dumper: yaml.SafeDumper, data: str) -> Any:
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    _Dumper.add_representer(str, _str_representer)

    # Write with a header comment
    header = "# policy/rules.yaml\n# Managed by Continuity Orchestrator — edit via admin panel or CLI\n\n"
    body = yaml.dump(data, Dumper=_Dumper, default_flow_style=False, sort_keys=False, allow_unicode=True)
    path.write_text(header + body, encoding="utf-8")


def _get_rule_summary(rule: Dict[str, Any]) -> Dict[str, Any]:
    """Build a summary dict for a rule."""
    rule_id = rule.get("id", "unknown")
    return {
        "id": rule_id,
        "description": rule.get("description", ""),
        "enabled": rule.get("enabled", True),
        "locked": rule_id in LOCKED_RULE_IDS,
        "stop": rule.get("stop", False),
    }


# ── CLI Command ───────────────────────────────────────────────────

@click.command("policy-constants")
@click.option("--json-output", "as_json", is_flag=True, help="Output as JSON")
@click.option("--set", "updates", multiple=True, help="KEY=VALUE pair to update (e.g. remind_1_at_minutes=120)")
@click.option("--enable", "enable_ids", multiple=True, help="Rule ID to enable")
@click.option("--disable", "disable_ids", multiple=True, help="Rule ID to disable")
@click.option("--preset", "preset_name", type=click.Choice(list(PRESETS.keys())), help="Apply a preset")
@click.option("--policy-dir", default="policy", help="Path to policy directory")
@click.pass_context
def policy_constants(
    ctx: click.Context,
    as_json: bool,
    updates: tuple,
    enable_ids: tuple,
    disable_ids: tuple,
    preset_name: Optional[str],
    policy_dir: str,
) -> None:
    """Read or update policy/rules.yaml constants and rule toggles."""
    root = ctx.obj["root"]
    data = _load_rules_yaml(root)

    constants = data.get("constants", {})
    rules = data.get("rules", [])

    is_write = bool(updates or enable_ids or disable_ids or preset_name)

    if is_write:
        # ── Apply preset ──
        if preset_name:
            preset = PRESETS[preset_name]
            # Apply constants
            preset_constants = preset.get("constants", preset)
            constants.update(preset_constants)
            data["constants"] = constants

            # Apply rule enables/disables
            disable_set = set(preset.get("disable", []))
            rule_map = {r["id"]: r for r in rules}
            for rule_id, rule in rule_map.items():
                if rule_id in LOCKED_RULE_IDS:
                    continue  # Never touch locked rules
                if rule_id in disable_set:
                    rule["enabled"] = False
                else:
                    # Presets without a disable list re-enable everything
                    rule.pop("enabled", None)  # defaults to True

            if not as_json:
                click.secho(f"✅ Applied preset: {preset_name}", fg="green")
                if disable_set:
                    for rid in sorted(disable_set):
                        click.secho(f"  🔴 Disabled: {rid}", fg="yellow")

        # ── Apply constant updates ──
        for pair in updates:
            if "=" not in pair:
                raise click.ClickException(f"Invalid format: {pair} (expected KEY=VALUE)")
            key, val_str = pair.split("=", 1)
            key = key.strip()

            if key not in constants:
                valid_keys = ", ".join(constants.keys())
                raise click.ClickException(f"Unknown constant: {key}. Valid: {valid_keys}")

            try:
                value = int(val_str.strip())
            except ValueError:
                raise click.ClickException(f"Value for {key} must be an integer, got: {val_str}")

            if value < 0:
                raise click.ClickException(f"Value for {key} must be non-negative, got: {value}")

            constants[key] = value

        data["constants"] = constants

        # ── Enable/disable rules ──
        rule_map = {r["id"]: r for r in rules}

        for rule_id in enable_ids:
            if rule_id not in rule_map:
                raise click.ClickException(f"Unknown rule: {rule_id}")
            rule_map[rule_id].pop("enabled", None)  # Remove field → defaults to True
            if not as_json:
                click.secho(f"  ✅ Enabled: {rule_id}", fg="green")

        for rule_id in disable_ids:
            if rule_id not in rule_map:
                raise click.ClickException(f"Unknown rule: {rule_id}")
            if rule_id in LOCKED_RULE_IDS:
                raise click.ClickException(f"Cannot disable locked rule: {rule_id}")
            rule_map[rule_id]["enabled"] = False
            if not as_json:
                click.secho(f"  🔴 Disabled: {rule_id}", fg="yellow")

        # Save
        _save_rules_yaml(root, data)
        if not as_json:
            click.secho("\n💾 Saved policy/rules.yaml", fg="green")

    # ── Output ──
    output = {
        "constants": constants,
        "rules": [_get_rule_summary(r) for r in rules],
        "presets": list(PRESETS.keys()),
    }

    if as_json:
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo()
        click.secho("📋 Escalation Policy Constants", bold=True)
        click.echo()

        click.echo("  Reminders (before deadline):")
        click.echo(f"    1st reminder ........ {constants.get('remind_1_at_minutes', '?')} min")
        click.echo(f"    2nd reminder ........ {constants.get('remind_2_at_minutes', '?')} min")
        click.echo(f"    Final warning ....... {constants.get('pre_release_at_minutes', '?')} min")
        click.echo()

        click.echo("  Disclosure (after deadline):")
        click.echo(f"    Partial delay ....... {constants.get('partial_after_overdue_minutes', '?')} min")
        click.echo(f"    Full delay .......... {constants.get('full_after_overdue_minutes', '?')} min")
        click.echo()

        click.echo("  Security:")
        click.echo(f"    Max failed attempts . {constants.get('max_failed_attempts', '?')}")
        click.echo()

        click.secho("  Rules:", bold=True)
        for r in rules:
            summary = _get_rule_summary(r)
            enabled = summary["enabled"]
            locked = summary["locked"]
            icon = "🔒" if locked else ("✅" if enabled else "🔴")
            state = "locked" if locked else ("on" if enabled else "OFF")
            click.echo(f"    {icon} {summary['id']:<42} [{state}]  {summary['description'][:50]}")
        click.echo()
