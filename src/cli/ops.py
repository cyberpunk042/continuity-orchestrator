"""
CLI ops commands — health, metrics, retry queue, circuit breakers.

Usage:
    python -m src.main health [--json]
    python -m src.main metrics [--format prometheus|json]
    python -m src.main retry-queue [--action status|clear]
    python -m src.main circuit-breakers [--reset]
"""

from __future__ import annotations

import click


@click.command("health")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--state-file", default="state/current.json", help="Path to state file")
@click.pass_context
def health(ctx: click.Context, as_json: bool, state_file: str) -> None:
    """Check system health status."""
    from ..observability.health import HealthChecker, HealthStatus

    root = ctx.obj["root"]
    state_path = root / state_file
    audit_path = root / "audit" / "ledger.ndjson"

    checker = HealthChecker(state_path=state_path, audit_path=audit_path)
    result = checker.check()

    if as_json:
        import json
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    # Status header
    status_colors = {
        HealthStatus.HEALTHY: ("✅", "green"),
        HealthStatus.DEGRADED: ("⚠️", "yellow"),
        HealthStatus.UNHEALTHY: ("❌", "red"),
    }
    icon, color = status_colors.get(result.status, ("❓", "white"))

    click.echo()
    click.secho(f"{icon} System Health: {result.status.value.upper()}", fg=color, bold=True)
    click.echo(f"   Uptime: {result.uptime_seconds:.0f}s")
    click.echo()

    # Components
    click.echo("Components:")
    for component in result.components:
        c_icon, c_color = status_colors.get(component.status, ("❓", "white"))
        click.echo(f"  {c_icon} ", nl=False)
        click.secho(f"{component.name}", fg=c_color, bold=True, nl=False)
        click.echo(f": {component.message}")
        if component.latency_ms:
            click.echo(f"      Latency: {component.latency_ms:.1f}ms")

    click.echo()

    # Exit code based on health
    if result.status == HealthStatus.UNHEALTHY:
        raise SystemExit(1)


@click.command("metrics")
@click.option("--format", "output_format", type=click.Choice(["prometheus", "json"]), default="prometheus")
@click.pass_context
def metrics_cmd(ctx: click.Context, output_format: str) -> None:
    """Export metrics for monitoring."""
    from ..observability.metrics import metrics

    if output_format == "json":
        import json
        click.echo(json.dumps(metrics.export_json(), indent=2))
    else:
        click.echo(metrics.export_prometheus())


@click.command("retry-queue")
@click.option("--action", type=click.Choice(["status", "clear"]), default="status")
@click.pass_context
def retry_queue_cmd(ctx: click.Context, action: str) -> None:
    """Manage the retry queue for failed actions."""
    from ..reliability.retry_queue import RetryQueue

    root = ctx.obj["root"]
    queue = RetryQueue(root / "state" / "retry_queue.json")

    if action == "status":
        stats = queue.get_stats()
        click.echo()
        click.echo("📋 Retry Queue Status")
        click.echo()
        click.echo(f"  Total items:   {stats['total_items']}")
        click.echo(f"  Pending now:   {stats['pending_now']}")

        if stats["by_adapter"]:
            click.echo()
            click.echo("  By adapter:")
            for adapter, count in stats["by_adapter"].items():
                click.echo(f"    {adapter}: {count}")

        click.echo()

    elif action == "clear":
        count = queue.clear()
        click.secho(f"✅ Cleared {count} items from retry queue", fg="green")


@click.command("circuit-breakers")
@click.option("--reset", "do_reset", is_flag=True, help="Reset all circuit breakers")
@click.pass_context
def circuit_breakers_cmd(ctx: click.Context, do_reset: bool) -> None:
    """View and manage circuit breakers."""
    from ..reliability.circuit_breaker import get_registry, CircuitState

    registry = get_registry()

    if do_reset:
        registry.reset_all()
        click.secho("✅ All circuit breakers reset", fg="green")
        return

    stats = registry.get_all_stats()

    if not stats:
        click.echo("No circuit breakers registered")
        return

    click.echo()
    click.echo("🔌 Circuit Breakers")
    click.echo()

    for name, data in stats.items():
        state = data["state"]
        color = {
            "closed": "green",
            "open": "red",
            "half_open": "yellow",
        }.get(state, "white")

        icon = {
            "closed": "🟢",
            "open": "🔴",
            "half_open": "🟡",
        }.get(state, "⚪")

        click.echo(f"  {icon} ", nl=False)
        click.secho(f"{name}", fg=color, bold=True, nl=False)
        click.echo(f": {state}")

        stats_data = data.get("stats", {})
        click.echo(f"      Success: {stats_data.get('success_count', 0)} | "
                   f"Failures: {stats_data.get('failure_count', 0)} | "
                   f"Rejected: {stats_data.get('rejected_count', 0)}")

    click.echo()
