"""
CLI config commands — adapter configuration checking and generation.

Usage:
    python -m src.main check-config
    python -m src.main config-status [--json] [--format cli|json|compact]
    python -m src.main generate-config [--output FILE]
"""

from __future__ import annotations

import click


@click.command("check-config")
@click.pass_context
def check_config(ctx: click.Context) -> None:
    """Check adapter configuration status."""
    from ..config.validator import ConfigValidator

    validator = ConfigValidator()
    results = validator.validate_all()

    click.echo("\n📋 Adapter Configuration Status\n")

    configured = []
    not_configured = []

    for name, status in sorted(results.items()):
        if status.configured:
            configured.append((name, status))
            click.secho(f"  ✓ {name}", fg="green", nl=False)
            click.echo(f" — {status.mode} mode")
        else:
            not_configured.append((name, status))
            click.secho(f"  ✗ {name}", fg="red", nl=False)
            if status.missing:
                click.echo(f" — missing: {', '.join(status.missing)}")
            else:
                click.echo(f" — not configured")

    click.echo()
    click.secho(f"Summary: {len(configured)} configured, {len(not_configured)} not configured", bold=True)

    if not_configured:
        click.echo("\n📖 Setup Guide:\n")
        for name, status in not_configured:
            if status.guidance:
                click.echo(f"  {name}:")
                click.echo(f"    → {status.guidance}")


@click.command("config-status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--format", "output_format", type=click.Choice(["cli", "json", "compact"]), default="cli", help="Output format")
@click.pass_context
def config_status(ctx: click.Context, as_json: bool, output_format: str) -> None:
    """
    Show comprehensive system and configuration status.

    This command provides a unified view of:
    - System state (stage, deadline)
    - Adapter configuration
    - Secrets status
    - Tool availability (gh, docker)

    Use --json for API-compatible output.
    """
    import json as json_lib
    from ..config.system_status import get_system_status, format_status_cli

    status = get_system_status()

    # JSON output
    if as_json or output_format == "json":
        click.echo(json_lib.dumps(status.to_dict(), indent=2))
        return

    # Compact output (for scripts)
    if output_format == "compact":
        click.echo(json_lib.dumps(status.to_dict()))
        return

    # CLI display
    click.echo(format_status_cli(status))


@click.command("generate-config")
@click.option("--output", "-o", help="Output file (default: stdout)")
@click.pass_context
def generate_config(ctx: click.Context, output: str) -> None:
    """
    Generate a CONTINUITY_CONFIG template.

    This creates a JSON template you can use as a single GitHub secret
    instead of configuring each adapter secret individually.
    """
    from ..config.loader import generate_master_config_template

    template = generate_master_config_template()

    if output:
        with open(output, "w") as f:
            f.write(template)
        click.secho(f"✅ Template written to {output}", fg="green")
        click.echo()
        click.echo("Next steps:")
        click.echo("  1. Edit the file with your credentials")
        click.echo("  2. Add as GitHub secret named CONTINUITY_CONFIG")
        click.echo("     (paste the entire JSON content)")
    else:
        click.echo()
        click.secho("CONTINUITY_CONFIG Template", bold=True)
        click.echo("─" * 40)
        click.echo()
        click.echo(template)
        click.echo()
        click.echo("─" * 40)
        click.echo()
        click.echo("To use this:")
        click.echo("  1. Copy the JSON above")
        click.echo("  2. Fill in your credentials")
        click.echo("  3. Go to GitHub → Settings → Secrets → Actions")
        click.echo("  4. Create secret named: CONTINUITY_CONFIG")
        click.echo("  5. Paste the JSON as the value")
