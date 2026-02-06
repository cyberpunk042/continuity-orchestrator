# Security Best Practices

This document outlines security considerations for running Continuity Orchestrator in production.

---

## Table of Contents

1. [Threat Model](#threat-model)
2. [Credential Security](#credential-security)
3. [Repository Security](#repository-security)
4. [Renewal Code Security](#renewal-code-security)
5. [Deployment Security](#deployment-security)
6. [Operational Security](#operational-security)
7. [Incident Response](#incident-response)

---

## Threat Model

### What Are We Protecting?

1. **The countdown state** — Preventing unauthorized resets or triggers
2. **Disclosure content** — Ensuring only you control what gets published
3. **Credentials** — API keys that could be used maliciously if exposed
4. **The renewal mechanism** — Ensuring only you can extend the deadline

### Threat Actors

| Actor | Motivation | Attack Vector |
|-------|------------|---------------|
| **Unauthorized accessor** | Trigger or prevent disclosure | Gain repository access |
| **State of actor** | Prevent disclosure | Seize devices, compel access |
| **Malicious insider** | Sabotage | Modify state or credentials |
| **Opportunistic attacker** | Credential theft | Leaked secrets in logs/history |

### Risk Levels by Deployment

| Deployment | Security Level | Considerations |
|------------|----------------|----------------|
| Local Docker | 🟡 Medium | Physical device security |
| GitHub Actions | 🟢 High | GitHub's security model |
| Self-hosted server | 🟡 Medium | Server hardening required |
| Shared hosting | 🔴 Low | Not recommended |

---

## Credential Security

### Secrets to Protect

| Secret | Risk if Exposed | Rotation Difficulty |
|--------|-----------------|---------------------|
| `RENEWAL_SECRET` | Unauthorized renewal | Easy — regenerate |
| `RELEASE_SECRET` | Unauthorized disclosure trigger | Easy — regenerate |
| `GITHUB_TOKEN` | Repository access | Medium — revoke and recreate |
| `RESEND_API_KEY` | Send emails as you | Medium — regenerate |
| `TWILIO_*` | Send SMS as you | Medium — regenerate |
| `X_*` / `REDDIT_*` | Post as you | Medium — revoke app |

### Best Practices

1. **Never commit secrets to git**
   ```bash
   # .gitignore should include:
   .env
   .env.local
   .env.*.local
   ```

2. **Use GitHub Secrets for Actions**
   ```bash
   # View required secrets
   python -m src.main export-secrets
   ```

3. **Rotate secrets regularly**
   - Renewal/Release codes: Every 6 months
   - API keys: Annually or after any suspected compromise

4. **Use unique credentials**
   - Don't reuse API keys from other projects
   - Create dedicated accounts for social posting

5. **Monitor API usage**
   - Enable alerts on Twilio, Resend, etc.
   - Watch for unexpected activity

### Secret Generation

```bash
# Generate high-entropy secrets
python -c "import secrets; print('RENEWAL_SECRET:', secrets.token_hex(32))"
python -c "import secrets; print('RELEASE_SECRET:', secrets.token_hex(32))"

# Never use:
# - Dictionary words
# - Personal information
# - Reused passwords

# You could also use a passsphrase for simplity but I would recommend a very long one in that case. 
```

---

## Repository Security

### GitHub Repository Settings

1. **Enable branch protection on `main`**
   - Require pull request reviews
   - Require status checks to pass
   - Disable force pushes

2. **Limit repository access**
   - Use private repository if content is sensitive
   - Audit collaborator list regularly
   - Use fine-grained personal access tokens

3. **Enable security alerts**
   - Dependabot for dependency vulnerabilities
   - Secret scanning to catch accidentally committed secrets

4. **Review Actions permissions**
   - Limit workflow permissions to minimum required
   - Review third-party actions before use

### Protecting State Files

The `state/current.json` file controls the countdown:

```json
{
  "escalation": {
    "state": "OK",           // Changing this affects behavior
    "state_entered_at_iso": "..."
  },
  "timer": {
    "deadline_iso": "..."    // Modifying extends/shortens countdown
  },
  "release": {
    "triggered": false       // Setting true initiates disclosure
  }
}
```

**Recommendations:**
- Monitor commits to `state/` directory
- Use GitHub's audit log to track changes
- Consider requiring reviews for state changes

---

## Renewal Code Security

The `RENEWAL_SECRET` is your lifeline. Treat it with extreme care.

### Storage Recommendations

| Method | Security | Accessibility | Recommendation |
|--------|----------|---------------|----------------|
| Password manager (1Password, Bitwarden) | 🟢 High | 🟢 High | ✅ Recommended |
| Encrypted note on phone | 🟡 Medium | 🟢 High | Acceptable |
| Physical paper in safe | 🟢 High | 🟡 Medium | Backup option |
| Memorization | 🟢 High | 🔴 Low | Not for 64-char codes |
| Plain text file | 🔴 Low | 🟢 High | ❌ Never |
| Email to yourself | 🔴 Low | 🟡 Medium | ❌ Never |

### Multiple Renewal Methods

Configure multiple ways to renew:

1. **Web dashboard** — Quick renewal via browser
2. **GitHub Actions workflow** — Run manually from GitHub
3. **CLI** — `python -m src.main renew`
4. **Trusted contact** — Share renewal code with someone you trust

### If You Lose Your Renewal Code

If you have repository access:
1. Generate new code: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Update `.env` locally
3. Update GitHub Secrets
4. Renew using CLI: `python -m src.main renew`

If you've lost all access:
- The countdown will continue
- Plan for this scenario by having backup access methods

---

## Deployment Security

### GitHub Actions (Recommended)

```yaml
# .github/workflows/cron.yml
permissions:
  contents: write    # Minimum needed
  pages: write
  id-token: write

concurrency:
  group: continuity-tick
  cancel-in-progress: false  # Prevent race conditions
```

**Security measures:**
- Secrets are encrypted at rest
- Logs automatically redact secrets
- Workflows run in isolated environments
- Audit logs track all runs

### Docker Deployment

```bash
# Use environment files, not command-line arguments
docker compose --env-file .env up -d

# Never:
docker run -e RENEWAL_SECRET=actual_secret ...  # Visible in process list
```

**Security measures:**
- Use Docker secrets for swarm deployments
- Limit container capabilities
- Run as non-root user
- Use read-only filesystem where possible

### Self-Hosted

If running on your own server:

1. **Use HTTPS** — Never expose renewal endpoints over HTTP
2. **Firewall** — Limit access to known IPs if possible
3. **Updates** — Keep OS and dependencies patched
4. **Monitoring** — Log and alert on suspicious activity
5. **Backups** — Ensure you can recover if server is compromised

---

## Operational Security

### Regular Audits

Perform monthly security checks:

```bash
# Check who has access
gh repo collaborator list

# Review recent changes to state
git log --oneline state/ audit/

# Verify secrets are not in git history  
git log --all --full-history -- "*.env" 
git log --all -p | grep -i "secret\|token\|password" | head -50
```

### Before Travel or Unavailability

1. **Extend deadline** — Give yourself buffer time
   ```bash
   python -m src.main set-deadline --hours 336  # 2 weeks
   ```

2. **Verify renewal access** — Test from mobile device
3. **Brief trusted contact** — Ensure backup renewal is possible
4. **Check integration status** — Ensure APIs are working

### Suspicious Activity Response

If you suspect compromise:

1. **Immediately rotate all secrets**
   ```bash
   # Regenerate and update
   python -c "import secrets; print(secrets.token_hex(32))"
   # Update in GitHub Secrets
   # Update in .env
   ```

2. **Review audit log**
   ```bash
   cat audit/ledger.ndjson | jq 'select(.event_type == "renewal" or .event_type == "release")'
   ```

3. **Check repository activity**
   - GitHub → Insights → Traffic
   - GitHub → Settings → Security → Audit log

4. **Revoke and regenerate API keys**

---

## Incident Response

### If Disclosure Triggers Accidentally

1. **Do NOT panic** — Some actions may be undoable
2. **Check what executed** — Review `audit/ledger.ndjson`
3. **Delete what you can** — Social posts, GitHub Pages
4. **Notify recipients** — Email recipients can be informed
5. **Learn and improve** — Adjust rules, lengthen deadlines

### If Credentials Are Exposed

1. **Rotate immediately** — Don't wait
2. **Check for unauthorized use** — API dashboards, GitHub audit log
3. **Invalidate old credentials** — Don't just create new ones
4. **Update all deployments** — Local, GitHub Secrets, Docker

### Emergency Contacts

Configure in your deployment:
- Trusted person who can renew on your behalf
- Backup email/phone for critical alerts
- Alternative access method to GitHub

---

## Security Checklist

Before going to production:

- [ ] All secrets are in GitHub Secrets or secure storage
- [ ] Repository is private (if content is sensitive)
- [ ] Branch protection is enabled on `main`
- [ ] `ADAPTER_MOCK_MODE` is explicitly set to `false`
- [ ] Renewal code is stored in password manager
- [ ] Renewal code is shared with trusted backup contact
- [ ] All integrations tested with real APIs
- [ ] Audit log is being written correctly
- [ ] You understand every action configured in `policy/plans/`
- [ ] You've tested the full escalation flow in mock mode
- [ ] You've reviewed the [DISCLAIMER](DISCLAIMER.md)

---

## Reporting Security Issues

If you discover a security vulnerability in Continuity Orchestrator:

1. **Do NOT open a public issue**
2. Email the maintainer directly (see repository owner)
3. Provide detailed reproduction steps
4. Allow reasonable time for a fix before disclosure

---

*Last updated: 2026-02-06*
