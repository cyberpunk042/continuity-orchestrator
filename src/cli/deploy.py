"""
CLI deployment commands — secrets export, stage explanation, simulation.

Usage:
    python -m src.main export-secrets [--format text|gh-cli]
    python -m src.main explain [--stage STAGE]
    python -m src.main simulate [--hours N]
"""

from __future__ import annotations

from datetime import datetime, timezone

import click


@click.command("export-secrets")
@click.option("--format", "-f", type=click.Choice(["text", "gh-cli"]), default="text", help="Output format")
def export_secrets(format: str):
    """Export secrets for GitHub Actions deployment.

    Shows which secrets need to be added to your GitHub repository
    for the scheduled tick workflow to run.
    """
    import os

    # Read current .env values
    secrets = {
        "RESEND_API_KEY": os.environ.get("RESEND_API_KEY", ""),
        "RESEND_FROM_EMAIL": os.environ.get("RESEND_FROM_EMAIL", ""),
        "TWILIO_ACCOUNT_SID": os.environ.get("TWILIO_ACCOUNT_SID", ""),
        "TWILIO_AUTH_TOKEN": os.environ.get("TWILIO_AUTH_TOKEN", ""),
        "TWILIO_FROM_NUMBER": os.environ.get("TWILIO_FROM_NUMBER", ""),
        "OPERATOR_SMS": os.environ.get("OPERATOR_SMS", ""),
        "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
        "X_API_KEY": os.environ.get("X_API_KEY", ""),
        "X_API_SECRET": os.environ.get("X_API_SECRET", ""),
        "X_ACCESS_TOKEN": os.environ.get("X_ACCESS_TOKEN", ""),
        "X_ACCESS_SECRET": os.environ.get("X_ACCESS_SECRET", ""),
        "REDDIT_CLIENT_ID": os.environ.get("REDDIT_CLIENT_ID", ""),
        "REDDIT_CLIENT_SECRET": os.environ.get("REDDIT_CLIENT_SECRET", ""),
        "REDDIT_USERNAME": os.environ.get("REDDIT_USERNAME", ""),
        "REDDIT_PASSWORD": os.environ.get("REDDIT_PASSWORD", ""),
    }

    # Core settings
    core = {
        "OPERATOR_EMAIL": os.environ.get("OPERATOR_EMAIL", ""),
        "PROJECT_NAME": os.environ.get("PROJECT_NAME", ""),
        "ADAPTER_MOCK_MODE": os.environ.get("ADAPTER_MOCK_MODE", "false"),
    }

    # Also need RENEWAL_SECRET for the renewal workflow
    renewal_secret = os.environ.get("RENEWAL_SECRET", "")

    # RENEWAL_TRIGGER_TOKEN for one-click renewal from website
    renewal_trigger_token = os.environ.get("RENEWAL_TRIGGER_TOKEN", "")

    repo = os.environ.get("GITHUB_REPOSITORY", "owner/repo")

    click.echo()
    click.secho("🔐 GitHub Actions Secrets", bold=True)
    click.echo()
    click.echo(f"Add these secrets to: https://github.com/{repo}/settings/secrets/actions")
    click.echo()

    if format == "gh-cli":
        click.echo("# Run these commands (requires gh CLI):")
        click.echo()
        for name, value in {**core, **secrets}.items():
            if value:
                # Mask the actual value
                click.echo(f'echo "{value}" | gh secret set {name}')
        if renewal_secret:
            click.echo(f'echo "{renewal_secret}" | gh secret set RENEWAL_SECRET')
        else:
            click.echo('# Generate a renewal secret:')
            click.echo('echo "$(openssl rand -hex 16)" | gh secret set RENEWAL_SECRET')
        if renewal_trigger_token:
            click.echo(f'echo "{renewal_trigger_token}" | gh secret set RENEWAL_TRIGGER_TOKEN')
        else:
            click.echo('# RENEWAL_TRIGGER_TOKEN not set - create a fine-grained PAT for one-click renewal')
        click.echo()
    else:
        click.secho("Required secrets:", bold=True)
        click.echo()

        # Show which are configured
        click.echo("  Core settings:")
        for name, value in core.items():
            if value:
                masked = value[:4] + "..." if len(value) > 4 else "***"
                click.secho(f"    ✅ {name}", fg="green", nl=False)
                click.echo(f" = {masked}")
            else:
                click.secho(f"    ⬚  {name}", fg="dim", nl=False)
                click.echo(" = (not set)")
        click.echo()

        click.echo("  Adapter credentials (only those you use):")
        for name, value in secrets.items():
            if value:
                masked = value[:6] + "..." if len(value) > 6 else "***"
                click.secho(f"    ✅ {name}", fg="green", nl=False)
                click.echo(f" = {masked}")
        click.echo()

        click.echo("  Renewal secret (for manual check-in):")
        if renewal_secret:
            click.secho("    ✅ RENEWAL_SECRET", fg="green", nl=False)
            click.echo(f" = {renewal_secret[:6]}...")
        else:
            click.secho("    ⚠️  RENEWAL_SECRET", fg="yellow", nl=False)
            click.echo(" = (generate one)")
            click.echo()
            click.echo('    Generate with: python -c "import secrets; print(secrets.token_hex(16))"')
        click.echo()

        click.echo("  One-click renewal from website (optional but recommended):")
        if renewal_trigger_token:
            click.secho("    ✅ RENEWAL_TRIGGER_TOKEN", fg="green", nl=False)
            click.echo(f" = {renewal_trigger_token[:12]}...")
        else:
            click.secho("    ⬚  RENEWAL_TRIGGER_TOKEN", fg="dim", nl=False)
            click.echo(" = (not set)")
            click.echo()
            click.echo("    Create a fine-grained PAT at: https://github.com/settings/tokens?type=beta")
            click.echo("    With ONLY 'Actions: Read and write' permission for this repo")
        click.echo()

    click.echo()
    click.secho("📋 Quick copy-paste guide:", bold=True)
    click.echo()
    click.echo("1. Go to your repository settings → Secrets → Actions")
    click.echo("2. Click 'New repository secret' for each secret")
    click.echo("3. Copy the name and value from your .env file")
    click.echo()
    click.echo("Alternatively, use the GitHub CLI:")
    click.echo("  python -m src.main export-secrets --format gh-cli")
    click.echo()


@click.command("explain")
@click.option("--policy-dir", default="policy", help="Path to policy directory")
@click.option("--stage", "-s", help="Show only a specific stage")
@click.pass_context
def explain_stages(ctx: click.Context, policy_dir: str, stage: str):
    """Show what happens at each escalation stage.

    Displays the full action plan for every stage, so you can understand
    exactly what will trigger when.
    """
    from ..policy.loader import load_policy

    root = ctx.obj["root"]
    policy_path = root / policy_dir

    # Load policy
    policy = load_policy(policy_path)

    # Get the plan
    plan = policy.plan
    if not plan:
        click.secho("❌ No plan found", fg="red")
        raise SystemExit(1)

    click.echo()
    click.secho("📋 Escalation Plan: " + (plan.plan_id or plan.name or "default"), bold=True)
    click.echo(f"   {plan.description or 'No description'}")
    click.echo()

    # Stage order
    stage_order = ["OK", "REMIND_1", "REMIND_2", "PRE_RELEASE", "PARTIAL", "FULL"]

    # Filter if specific stage requested
    if stage:
        stage_order = [s for s in stage_order if s.upper() == stage.upper()]
        if not stage_order:
            click.secho(f"❌ Unknown stage: {stage}", fg="red")
            click.echo("   Valid stages: OK, REMIND_1, REMIND_2, PRE_RELEASE, PARTIAL, FULL")
            raise SystemExit(1)

    for stage_name in stage_order:
        stage_config = plan.stages.get(stage_name)

        if not stage_config:
            continue

        # Color based on severity
        if stage_name == "OK":
            color = "green"
            icon = "✅"
        elif stage_name in ["REMIND_1", "REMIND_2"]:
            color = "yellow"
            icon = "⚠️"
        elif stage_name == "PRE_RELEASE":
            color = "yellow"
            icon = "🔔"
        elif stage_name == "PARTIAL":
            color = "red"
            icon = "🚨"
        else:  # FULL
            color = "red"
            icon = "💀"

        click.secho("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", bold=True)
        click.secho(f"{icon} {stage_name}", fg=color, bold=True)
        click.echo(f"   {stage_config.description}")
        click.echo()

        if not stage_config.actions:
            click.echo("   No actions configured for this stage.")
        else:
            click.echo(f"   Actions ({len(stage_config.actions)}):")
            for action in stage_config.actions:
                adapter_icon = {
                    "email": "📧",
                    "sms": "📱",
                    "x": "🐦",
                    "reddit": "🔴",
                    "webhook": "🔗",
                    "github_surface": "🐙",
                    "article_publish": "📄",
                    "persistence_api": "💾",
                }.get(action.adapter, "⚙️")

                click.echo(f"   {adapter_icon} {action.id}")
                click.echo(f"      Adapter: {action.adapter}")
                click.echo(f"      Channel: {action.channel}")
                if action.template:
                    click.echo(f"      Template: {action.template}")
                if hasattr(action, 'constraints') and action.constraints:
                    try:
                        c_dict = action.constraints.model_dump(exclude_defaults=True)
                        if c_dict:
                            constraints = ", ".join(f"{k}={v}" for k, v in c_dict.items())
                            click.echo(f"      Constraints: {constraints}")
                    except Exception:
                        pass
        click.echo()

    click.secho("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", bold=True)
    click.echo()

    # Show triggers
    click.secho("📅 When do stages trigger?", bold=True)
    click.echo()
    click.echo("   Based on policy/rules.yaml, checked every tick:")
    click.echo()

    # Load rules - policy.rules is RulesPolicy, .rules is the list
    try:
        rules_list = policy.rules.rules if hasattr(policy.rules, 'rules') else []
        for rule in rules_list[:10]:  # First 10 rules
            if hasattr(rule, 'then') and rule.then and hasattr(rule.then, 'transition_to') and rule.then.transition_to:
                click.echo(f"   • {rule.id}")
                if hasattr(rule, 'description') and rule.description:
                    click.echo(f"     {rule.description}")
    except Exception:
        click.echo("   (See policy/rules.yaml for full rule definitions)")

    click.echo()
    click.echo("To modify this plan: edit policy/plans/default.yaml")
    click.echo("To modify triggers: edit policy/rules.yaml")
    click.echo()


def _run_simulation(
    state,
    policy_dir,
    hours: int = 72,
    step_minutes: int = 15,
):
    """Run simulated ticks forward in time and return transition events.

    Deep-copies the state and steps forward in ``step_minutes`` increments,
    evaluating policy rules at each step.  Only state transitions (set_state)
    are applied — no adapter actions are executed.

    Args:
        state: Current State object (will NOT be mutated).
        policy_dir: Path to the policy directory.
        hours: How many hours to simulate.
        step_minutes: Resolution of the simulation (minutes per step).

    Returns:
        dict with ``simulation`` metadata and ``events`` list.
    """
    import copy
    from datetime import timedelta

    from ..engine.rules import evaluate_rules
    from ..engine.state import apply_rule_mutation
    from ..engine.time_eval import compute_time_fields
    from ..policy.loader import load_rules

    rules_policy = load_rules(policy_dir)
    sim_state = copy.deepcopy(state)

    # Clear the renewal flag — we're simulating "what if you DON'T renew"
    sim_state.renewal.renewed_this_tick = False

    now = datetime.now(timezone.utc)
    events = []

    for minute in range(0, hours * 60 + 1, step_minutes):
        sim_time = now + timedelta(minutes=minute)

        # Recompute time-derived fields for the simulated instant
        compute_time_fields(sim_state, sim_time)

        # Evaluate every enabled rule
        matched = evaluate_rules(sim_state, rules_policy)

        # Apply only state mutations (set_state) — skip adapter actions
        for rule in matched:
            result = apply_rule_mutation(sim_state, rule, sim_time)
            if result["state_changed"]:
                events.append({
                    "minute": minute,
                    "time": sim_time.isoformat().replace("+00:00", "Z"),
                    "from_state": result.get("fields_cleared", []),  # unused
                    "from": events[-1]["to"] if events else state.escalation.state,
                    "to": result["new_state"],
                    "rule": rule.id,
                })

        # Once we hit FULL, nothing further happens
        if sim_state.escalation.state == "FULL":
            break

    # Re-derive 'from' properly from event chain
    for i, ev in enumerate(events):
        if i == 0:
            ev["from"] = state.escalation.state
        else:
            ev["from"] = events[i - 1]["to"]
        ev.pop("from_state", None)  # Clean up temp field

    return {
        "simulation": {
            "from": now.isoformat().replace("+00:00", "Z"),
            "to": (now + timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
            "hours": hours,
            "current_state": state.escalation.state,
            "deadline": state.timer.deadline_iso,
        },
        "events": events,
    }


@click.command("simulate")
@click.option("--hours", "-h", default=72, help="Hours to simulate")
@click.option("--state-file", default="state/current.json", help="Path to state file")
@click.option("--policy-dir", default="policy", help="Path to policy directory")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON for API consumption")
@click.pass_context
def simulate_timeline(ctx: click.Context, hours: int, state_file: str, policy_dir: str, as_json: bool):
    """Simulate the escalation timeline from now.

    Shows what would happen if you don't renew — when each stage would trigger.
    Uses actual policy rules and current state for accurate predictions.
    """
    import json as _json

    from ..persistence.state_file import load_state

    root = ctx.obj["root"]
    state_path = root / state_file

    if not state_path.exists():
        click.secho("❌ No state file found. Run init first.", fg="red")
        click.echo("   python -m src.main init")
        raise SystemExit(1)

    state = load_state(state_path)
    policy_path = root / policy_dir

    result = _run_simulation(state, policy_path, hours=hours)

    # JSON mode — machine-readable output for the API / admin UI
    if as_json:
        click.echo(_json.dumps(result, indent=2))
        return

    # ── Pretty CLI output ──────────────────────────────────────
    now = datetime.now(timezone.utc)
    deadline_str = state.timer.deadline_iso
    if isinstance(deadline_str, str):
        from dateutil.parser import parse
        deadline_dt = parse(deadline_str)
    else:
        deadline_dt = deadline_str

    click.echo()
    click.secho("🔮 Escalation Timeline Simulation", bold=True)
    click.echo()
    click.echo(f"   Current time:  {now.strftime('%Y-%m-%d %H:%M UTC')}")
    click.echo(f"   Deadline:      {deadline_dt.strftime('%Y-%m-%d %H:%M UTC')}")
    click.echo(f"   Current stage: {state.escalation.state}")
    click.echo(f"   Simulating:    {hours}h window")
    click.echo()

    events = result["events"]

    if not events:
        click.secho("   ✅ No state changes in this window.", fg="green")
        click.echo("      System stays at " + state.escalation.state + ".")
    else:
        click.secho("   If you DON'T renew:", bold=True)
        click.echo()

        # Stage colors
        stage_colors = {
            "OK": "green", "REMIND_1": "yellow", "REMIND_2": "yellow",
            "PRE_RELEASE": "yellow", "PARTIAL": "red", "FULL": "red",
        }

        for ev in events:
            from dateutil.parser import parse as dt_parse
            ev_time = dt_parse(ev["time"])
            delta = ev_time - now
            delta_str = _format_delta(delta)

            color = stage_colors.get(ev["to"], "white")
            click.echo(f"   ", nl=False)
            click.secho(f"{ev['from']} → {ev['to']}", fg=color, bold=True, nl=False)
            click.echo(f"  at {ev_time.strftime('%a %d %b %H:%M UTC')}  ({delta_str})")
            click.echo(f"      Rule: {ev['rule']}")

        click.echo()

        # Summary warning
        final_state = events[-1]["to"]
        final_time = events[-1]["time"]
        from dateutil.parser import parse as dt_parse2
        final_delta = dt_parse2(final_time) - now
        final_delta_str = _format_delta(final_delta)

        if final_state == "FULL":
            click.secho(f"   ⚠️  FULL disclosure in {final_delta_str}!", fg="red", bold=True)
        elif final_state in ("PARTIAL", "PRE_RELEASE"):
            click.secho(f"   ⚠️  Reaches {final_state} in {final_delta_str}", fg="yellow", bold=True)
        else:
            click.secho(f"   ℹ️  Reaches {final_state} in {final_delta_str}", fg="cyan")

    click.echo()
    click.echo("   To renew and reset the deadline:")
    click.echo("     python -m src.main renew --hours 48")
    click.echo()


def _format_delta(delta) -> str:
    """Format a timedelta as a human-readable string like '2d 5h 30m'."""
    total_minutes = int(delta.total_seconds() / 60)
    if total_minutes < 0:
        return "already past"
    days = total_minutes // (24 * 60)
    remaining = total_minutes % (24 * 60)
    hrs = remaining // 60
    mins = remaining % 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hrs:
        parts.append(f"{hrs}h")
    if mins or not parts:
        parts.append(f"{mins}m")
    return " ".join(parts)
