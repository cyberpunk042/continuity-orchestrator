"""
CLI site commands — static site generation and archival.

Usage:
    python -m src.main build-site [--output DIR] [--clean/--no-clean] [--archive/--no-archive]
"""

from __future__ import annotations

import click


@click.command("build-site")
@click.option(
    "--output",
    "-o",
    type=str,
    default="public",
    help="Output directory for the static site",
)
@click.option(
    "--clean/--no-clean",
    default=True,
    help="Clean output directory before building",
)
@click.option(
    "--archive/--no-archive",
    default=None,
    help="Archive to Internet Archive after build (default: uses ARCHIVE_ENABLED env)",
)
@click.pass_context
def build_site(ctx: click.Context, output: str, clean: bool, archive: bool) -> None:
    """Build static site from current state."""
    import json
    import os
    from pathlib import Path

    from ..persistence.state_file import load_state
    from ..site.generator import SiteGenerator

    root = ctx.obj["root"]
    state_path = root / "state" / "current.json"

    click.echo(f"Loading state from {state_path}")
    state = load_state(state_path)

    # Load audit entries
    audit_path = root / "audit" / "ledger.ndjson"
    audit_entries = []
    if audit_path.exists():
        with open(audit_path) as f:
            for line in f:
                if line.strip():
                    try:
                        audit_entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    click.echo(f"Building site to {output}/")
    generator = SiteGenerator(output_dir=root / output)
    result = generator.build(
        state=state,
        audit_entries=audit_entries,
        clean=clean,
    )

    click.secho(f"✓ Site built: {result['files_generated']} files", fg="green")
    click.echo(f"  Output: {result['output_dir']}")

    for f in result['files'][:5]:
        click.echo(f"  - {Path(f).name}")

    if len(result['files']) > 5:
        click.echo(f"  ... and {len(result['files']) - 5} more")

    # Archive to Internet Archive if enabled
    should_archive = archive
    if should_archive is None:
        # Check env var
        should_archive = os.environ.get("ARCHIVE_ENABLED", "false").lower() in ("true", "1", "yes")

    if should_archive:
        click.echo()
        click.echo("📦 Archiving to Internet Archive...")
        try:
            from ..adapters.internet_archive import archive_url_now

            # Determine base URL
            archive_base = os.environ.get("ARCHIVE_URL")
            if not archive_base:
                repo = os.environ.get("GITHUB_REPOSITORY")
                if repo:
                    parts = repo.split("/")
                    archive_base = f"https://{parts[0]}.github.io/{parts[1]}"
                else:
                    click.secho("  ⚠ No ARCHIVE_URL or GITHUB_REPOSITORY set, skipping archive", fg="yellow")
                    return

            # Strip trailing slash for clean joining
            archive_base = archive_base.rstrip("/")

            # Get all archivable pages
            archivable_paths = SiteGenerator.get_archivable_paths(root / output)
            click.echo(f"  Found {len(archivable_paths)} page(s) to archive")

            success_count = 0
            for i, path in enumerate(archivable_paths):
                page_url = f"{archive_base}/{path}" if path else f"{archive_base}/"
                label = path or "index"
                click.echo(f"  [{i+1}/{len(archivable_paths)}] {label}...", nl=False)

                archive_result = archive_url_now(page_url)

                if archive_result.get("success"):
                    click.secho(" ✓", fg="green")
                    success_count += 1
                else:
                    click.secho(f" ✗ {archive_result.get('error', '?')}", fg="red")

                # Rate limit: archive.org allows ~3/min anonymous
                if i < len(archivable_paths) - 1:
                    import time as time_mod
                    time_mod.sleep(5)

            click.secho(f"  Archived {success_count}/{len(archivable_paths)} pages", fg="green" if success_count == len(archivable_paths) else "yellow")
        except Exception as e:
            click.secho(f"  ✗ Archive error: {e}", fg="red")
