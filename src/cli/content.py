"""
CLI content commands — encryption, key management, and article status.

Usage:
    python -m src.main content-keygen
    python -m src.main content-encrypt [--slug SLUG | --all] [--skip-public]
    python -m src.main content-decrypt [--slug SLUG | --all] [--dry-run]
    python -m src.main content-status
"""

from __future__ import annotations

import click


@click.command("content-keygen")
def content_keygen() -> None:
    """Generate a new CONTENT_ENCRYPTION_KEY.

    Outputs a cryptographically secure passphrase suitable for
    use as CONTENT_ENCRYPTION_KEY in .env or GitHub Secrets.
    """
    from ..content.crypto import generate_key

    key = generate_key()

    click.echo()
    click.secho("🔑 Generated Content Encryption Key", fg="green", bold=True)
    click.echo()
    click.echo(f"  {key}")
    click.echo()
    click.echo("Add this to your .env file:")
    click.secho(f"  CONTENT_ENCRYPTION_KEY={key}", fg="cyan")
    click.echo()
    click.echo("And to GitHub Secrets:")
    click.secho("  gh secret set CONTENT_ENCRYPTION_KEY -R <owner>/<repo>", fg="cyan")
    click.echo()
    click.secho("⚠  Store this key safely — if lost, encrypted articles cannot be recovered.", fg="yellow")


@click.command("content-status")
@click.pass_context
def content_status(ctx: click.Context) -> None:
    """Show encryption status of all articles."""
    import json

    from ..content.crypto import ENV_VAR, get_encryption_key, is_encrypted

    root = ctx.obj["root"]
    articles_dir = root / "content" / "articles"

    # Check key availability
    key = get_encryption_key()
    click.echo()
    if key:
        click.secho("🔑 Encryption key: ✅ Configured", fg="green")
    else:
        click.secho(f"🔑 Encryption key: ❌ Not set ({ENV_VAR})", fg="yellow")
    click.echo()

    if not articles_dir.exists():
        click.echo("  No articles directory found.")
        return

    json_files = sorted(articles_dir.glob("*.json"))
    if not json_files:
        click.echo("  No articles found.")
        return

    # Load manifest for stage info
    try:
        from ..site.manifest import ContentManifest
        manifest = ContentManifest.load()
    except Exception:
        manifest = None

    # Display table
    click.echo(f"  {'Article':<30} {'Status':<15} {'Stage':<12}")
    click.echo(f"  {'─' * 30} {'─' * 15} {'─' * 12}")

    encrypted_count = 0
    plaintext_count = 0

    for path in json_files:
        slug = path.stem
        try:
            data = json.loads(path.read_text())
            encrypted = is_encrypted(data)
        except Exception:
            click.echo(f"  {slug:<30} {'⚠ error':<15}")
            continue

        if encrypted:
            status = "🔒 encrypted"
            encrypted_count += 1
        else:
            status = "📄 plaintext"
            plaintext_count += 1

        # Get min_stage from manifest
        stage = "—"
        if manifest:
            entry = manifest.get_article(slug)
            if entry:
                stage = entry.visibility.min_stage

        click.echo(f"  {slug:<30} {status:<15} {stage:<12}")

    click.echo()
    click.echo(f"  Total: {len(json_files)} articles "
               f"({encrypted_count} encrypted, {plaintext_count} plaintext)")


@click.command("content-encrypt")
@click.option("--slug", "-s", default=None, help="Encrypt a specific article by slug")
@click.option("--all", "encrypt_all", is_flag=True, help="Encrypt all plaintext articles")
@click.option("--skip-public", is_flag=True,
              help="Skip articles with min_stage OK (public pages)")
@click.pass_context
def content_encrypt(ctx: click.Context, slug: str, encrypt_all: bool, skip_public: bool) -> None:
    """Encrypt article files for safe storage in a public repository.

    Encrypts plaintext Editor.js JSON files using AES-256-GCM.
    Requires CONTENT_ENCRYPTION_KEY to be set in .env or environment.
    """
    import json

    from ..content.crypto import (
        ENV_VAR,
        encrypt_content,
        get_encryption_key,
        is_encrypted,
    )

    if not slug and not encrypt_all:
        click.secho("Error: specify --slug <name> or --all", fg="red")
        raise SystemExit(1)

    root = ctx.obj["root"]
    articles_dir = root / "content" / "articles"

    key = get_encryption_key()
    if not key:
        click.secho(f"Error: {ENV_VAR} not set. Run 'content-keygen' first.", fg="red")
        raise SystemExit(1)

    # Load manifest for --skip-public
    manifest = None
    if skip_public:
        try:
            from ..site.manifest import ContentManifest
            manifest = ContentManifest.load()
        except Exception:
            pass

    if slug:
        targets = [articles_dir / f"{slug}.json"]
    else:
        targets = sorted(articles_dir.glob("*.json"))

    encrypted_count = 0
    skipped_count = 0

    for path in targets:
        if not path.exists():
            click.secho(f"  ✗ {path.stem}: file not found", fg="red")
            continue

        try:
            data = json.loads(path.read_text())
        except Exception as e:
            click.secho(f"  ✗ {path.stem}: failed to read ({e})", fg="red")
            continue

        if is_encrypted(data):
            click.echo(f"  ⊘ {path.stem}: already encrypted")
            skipped_count += 1
            continue

        # Skip public articles if requested
        if skip_public and manifest:
            entry = manifest.get_article(path.stem)
            if entry and entry.visibility.min_stage == "OK":
                click.echo(f"  ⊘ {path.stem}: skipped (public, min_stage=OK)")
                skipped_count += 1
                continue

        # Encrypt
        envelope = encrypt_content(data, key)
        path.write_text(
            json.dumps(envelope, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        click.secho(f"  ✓ {path.stem}: encrypted", fg="green")
        encrypted_count += 1

    click.echo()
    total = encrypted_count + skipped_count
    click.echo(f"  Encrypted {encrypted_count} of {total} article(s)"
               + (f" (skipped {skipped_count})" if skipped_count else ""))


@click.command("content-decrypt")
@click.option("--slug", "-s", default=None, help="Decrypt a specific article by slug")
@click.option("--all", "decrypt_all", is_flag=True, help="Decrypt all encrypted articles")
@click.option("--dry-run", is_flag=True, help="Show decrypted content without writing to disk")
@click.pass_context
def content_decrypt(
    ctx: click.Context,
    slug: str,
    decrypt_all: bool,
    dry_run: bool,
) -> None:
    """Decrypt encrypted article files back to plaintext.

    Useful for debugging or removing encryption from articles.
    Use --dry-run to preview without modifying files.
    """
    import json

    from ..content.crypto import (
        ENV_VAR,
        decrypt_content,
        get_encryption_key,
        is_encrypted,
    )

    if not slug and not decrypt_all:
        click.secho("Error: specify --slug <name> or --all", fg="red")
        raise SystemExit(1)

    root = ctx.obj["root"]
    articles_dir = root / "content" / "articles"

    key = get_encryption_key()
    if not key:
        click.secho(f"Error: {ENV_VAR} not set.", fg="red")
        raise SystemExit(1)

    if slug:
        targets = [articles_dir / f"{slug}.json"]
    else:
        targets = sorted(articles_dir.glob("*.json"))

    decrypted_count = 0
    skipped_count = 0

    for path in targets:
        if not path.exists():
            click.secho(f"  ✗ {path.stem}: file not found", fg="red")
            continue

        try:
            data = json.loads(path.read_text())
        except Exception as e:
            click.secho(f"  ✗ {path.stem}: failed to read ({e})", fg="red")
            continue

        if not is_encrypted(data):
            click.echo(f"  ⊘ {path.stem}: already plaintext")
            skipped_count += 1
            continue

        try:
            content = decrypt_content(data, key)
        except Exception as e:
            click.secho(f"  ✗ {path.stem}: decryption failed ({e})", fg="red")
            continue

        if dry_run:
            click.secho(f"  📖 {path.stem} (dry-run):", fg="cyan")
            # Show first few blocks
            blocks = content.get("blocks", [])
            for block in blocks[:3]:
                btype = block.get("type", "?")
                text = block.get("data", {}).get("text", "")[:80]
                click.echo(f"     [{btype}] {text}")
            if len(blocks) > 3:
                click.echo(f"     ... and {len(blocks) - 3} more blocks")
            click.echo()
        else:
            path.write_text(
                json.dumps(content, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            click.secho(f"  ✓ {path.stem}: decrypted", fg="green")

        decrypted_count += 1

    click.echo()
    action = "Previewed" if dry_run else "Decrypted"
    total = decrypted_count + skipped_count
    click.echo(f"  {action} {decrypted_count} of {total} article(s)"
               + (f" (skipped {skipped_count})" if skipped_count else ""))
