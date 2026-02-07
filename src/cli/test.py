"""
CLI test commands — verify each adapter works with real API calls.

Usage:
    python -m src.main test email [--to EMAIL]
    python -m src.main test sms [--to NUMBER]
    python -m src.main test webhook --url URL
    python -m src.main test github [--repo OWNER/REPO]
    python -m src.main test all
"""

from __future__ import annotations

import click


@click.group()
def test():
    """Test individual adapters with real API calls."""
    pass


@test.command("email")
@click.option("--to", "-t", help="Email address to send to (default: OPERATOR_EMAIL)")
@click.option("--subject", "-s", default="Continuity Orchestrator Test", help="Email subject")
@click.option("--body", "-b", default="This is a test email from Continuity Orchestrator.", help="Email body")
def test_email(to: str, subject: str, body: str):
    """Send a test email via Resend."""
    import os

    # Check configuration
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        click.secho("❌ RESEND_API_KEY not set", fg="red")
        click.echo("   Set it in your .env file or export it:")
        click.echo("   export RESEND_API_KEY=re_xxxxx")
        raise SystemExit(1)

    to_email = to or os.environ.get("OPERATOR_EMAIL")
    if not to_email:
        click.secho("❌ No email address specified", fg="red")
        click.echo("   Use --to <email> or set OPERATOR_EMAIL in .env")
        raise SystemExit(1)

    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    click.echo()
    click.secho("📧 Testing Email (Resend)", bold=True)
    click.echo(f"   From: {from_email}")
    click.echo(f"   To: {to_email}")
    click.echo(f"   Subject: {subject}")
    click.echo()

    try:
        import resend
        resend.api_key = api_key

        result = resend.Emails.send({
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "text": body,
            "html": f"<p>{body}</p><p><small>Sent by Continuity Orchestrator test command.</small></p>",
        })

        email_id = result.get("id") if isinstance(result, dict) else str(result)
        click.secho(f"✅ Email sent successfully!", fg="green")
        click.echo(f"   Email ID: {email_id}")
        click.echo()
        click.echo(f"   Check your inbox at {to_email}")

    except ImportError:
        click.secho("❌ resend package not installed", fg="red")
        click.echo("   pip install resend")
        raise SystemExit(1)
    except Exception as e:
        click.secho(f"❌ Email failed: {e}", fg="red")
        raise SystemExit(1)


@test.command("sms")
@click.option("--to", "-t", help="Phone number to send to (default: OPERATOR_SMS)")
@click.option("--message", "-m", default="Continuity Orchestrator test message", help="SMS message")
def test_sms(to: str, message: str):
    """Send a test SMS via Twilio."""
    import os

    # Check configuration
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")

    missing = []
    if not account_sid:
        missing.append("TWILIO_ACCOUNT_SID")
    if not auth_token:
        missing.append("TWILIO_AUTH_TOKEN")
    if not from_number:
        missing.append("TWILIO_FROM_NUMBER")

    if missing:
        click.secho(f"❌ Missing: {', '.join(missing)}", fg="red")
        click.echo("   Set these in your .env file")
        raise SystemExit(1)

    to_number = to or os.environ.get("OPERATOR_SMS")
    if not to_number:
        click.secho("❌ No phone number specified", fg="red")
        click.echo("   Use --to <number> or set OPERATOR_SMS in .env")
        raise SystemExit(1)

    click.echo()
    click.secho("📱 Testing SMS (Twilio)", bold=True)
    click.echo(f"   From: {from_number}")
    click.echo(f"   To: {to_number}")
    click.echo(f"   Message: {message}")
    click.echo()

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)

        result = client.messages.create(
            body=message,
            from_=from_number,
            to=to_number,
        )

        click.secho(f"✅ SMS sent successfully!", fg="green")
        click.echo(f"   Message SID: {result.sid}")
        click.echo(f"   Status: {result.status}")

    except ImportError:
        click.secho("❌ twilio package not installed", fg="red")
        click.echo("   pip install twilio")
        raise SystemExit(1)
    except Exception as e:
        click.secho(f"❌ SMS failed: {e}", fg="red")
        raise SystemExit(1)


@test.command("webhook")
@click.option("--url", "-u", required=True, help="Webhook URL to POST to")
@click.option("--payload", "-p", default='{"test": true, "source": "continuity-orchestrator"}', help="JSON payload")
def test_webhook(url: str, payload: str):
    """Send a test webhook POST."""
    import json

    click.echo()
    click.secho("🔗 Testing Webhook", bold=True)
    click.echo(f"   URL: {url}")
    click.echo(f"   Payload: {payload}")
    click.echo()

    try:
        import httpx

        data = json.loads(payload)
        response = httpx.post(url, json=data, timeout=30)

        if response.status_code < 400:
            click.secho(f"✅ Webhook successful!", fg="green")
            click.echo(f"   Status: {response.status_code}")
            click.echo(f"   Response: {response.text[:200]}")
        else:
            click.secho(f"⚠️ Webhook returned error", fg="yellow")
            click.echo(f"   Status: {response.status_code}")
            click.echo(f"   Response: {response.text[:200]}")

    except ImportError:
        click.secho("❌ httpx package not installed", fg="red")
        click.echo("   pip install httpx")
        raise SystemExit(1)
    except json.JSONDecodeError:
        click.secho("❌ Invalid JSON payload", fg="red")
        raise SystemExit(1)
    except Exception as e:
        click.secho(f"❌ Webhook failed: {e}", fg="red")
        raise SystemExit(1)


@test.command("github")
@click.option("--repo", "-r", help="Repository (owner/repo) — default: GITHUB_REPOSITORY")
def test_github(repo: str):
    """Verify GitHub token and repository access."""
    import os

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        click.secho("❌ GITHUB_TOKEN not set", fg="red")
        click.echo("   Set it in your .env file")
        raise SystemExit(1)

    repository = repo or os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        click.secho("❌ No repository specified", fg="red")
        click.echo("   Use --repo owner/repo or set GITHUB_REPOSITORY in .env")
        raise SystemExit(1)

    click.echo()
    click.secho("🐙 Testing GitHub", bold=True)
    click.echo(f"   Token: {token[:10]}...")
    click.echo(f"   Repository: {repository}")
    click.echo()

    try:
        import httpx

        # Test token by getting user info
        headers = {"Authorization": f"Bearer {token}"}

        user_response = httpx.get("https://api.github.com/user", headers=headers, timeout=30)
        if user_response.status_code != 200:
            click.secho(f"❌ Token invalid: {user_response.status_code}", fg="red")
            raise SystemExit(1)

        user_data = user_response.json()
        click.secho(f"✅ Token valid!", fg="green")
        click.echo(f"   User: {user_data.get('login')}")

        # Test repository access
        repo_response = httpx.get(
            f"https://api.github.com/repos/{repository}",
            headers=headers,
            timeout=30,
        )

        if repo_response.status_code == 200:
            repo_data = repo_response.json()
            click.secho(f"✅ Repository accessible!", fg="green")
            click.echo(f"   Name: {repo_data.get('full_name')}")
            click.echo(f"   Visibility: {repo_data.get('visibility')}")
        elif repo_response.status_code == 404:
            click.secho(f"⚠️ Repository not found or no access", fg="yellow")
            click.echo(f"   Check repository exists and token has permissions")
        else:
            click.secho(f"⚠️ Repository check failed: {repo_response.status_code}", fg="yellow")

    except ImportError:
        click.secho("❌ httpx package not installed", fg="red")
        click.echo("   pip install httpx")
        raise SystemExit(1)
    except Exception as e:
        click.secho(f"❌ GitHub test failed: {e}", fg="red")
        raise SystemExit(1)


@test.command("all")
def test_all():
    """Show configuration status for all adapters."""
    from ..config.validator import ConfigValidator

    click.echo()
    click.secho("🧪 Adapter Configuration Status", bold=True)
    click.echo()

    validator = ConfigValidator()
    results = validator.validate_all()

    for name, status in sorted(results.items()):
        if status.configured:
            if status.mode == "real":
                click.secho(f"  ✅ {name}", fg="green", nl=False)
                click.echo(f" — ready (real mode)")
            else:
                click.secho(f"  ⚠️  {name}", fg="yellow", nl=False)
                click.echo(f" — configured but mock mode enabled")
        else:
            click.secho(f"  ❌ {name}", fg="red", nl=False)
            if status.missing:
                click.echo(f" — missing: {', '.join(status.missing)}")
            else:
                click.echo(f" — not configured")

    click.echo()
    click.echo("To test an adapter:")
    click.echo("  python -m src.main test email")
    click.echo("  python -m src.main test sms")
    click.echo("  python -m src.main test webhook --url https://example.com/hook")
    click.echo("  python -m src.main test github")
    click.echo()
