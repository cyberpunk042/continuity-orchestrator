# ⚠️ IMPORTANT DISCLAIMER

**Please read this entire document before using Continuity Orchestrator.**

---

## Nature of This Software

Continuity Orchestrator is an **automated disclosure system** (commonly known as a "deadman switch"). It is designed to automatically execute pre-configured actions—including publishing documents, sending emails, posting to social media, and triggering webhooks—if you fail to check in within a specified timeframe.

**This is powerful automation software.** Once triggered, actions may be **irreversible**.

---

## Critical Warnings

### ⚡ Irreversibility

- **Published content cannot be unpublished.** Once documents are posted to GitHub Pages, social media, or sent via email, they exist in the public domain and may be archived, screenshot, or redistributed by third parties.
  
- **Emails and SMS cannot be unsent.** Recipients receive notifications immediately upon execution.

- **Social media posts spread rapidly.** Even if deleted, posts may have already been seen, shared, or archived.

### ⏱️ Timing Failures

- **You must renew before the deadline.** If you are unable to access the system due to internet outage, travel, hospitalization, or any other reason, the countdown will continue.

- **Scheduled execution depends on external services.** GitHub Actions, cron jobs, and cloud services may experience outages or delays. The system cannot guarantee exact timing.

- **Clock drift and timezone issues** can cause unexpected behavior. Always verify deadlines in UTC.

### 🔐 Security Considerations

- **API keys and tokens grant significant access.** Compromised credentials could allow unauthorized disclosure or system manipulation.

- **Repository access means full control.** Anyone with write access to your repository can modify state, trigger releases, or disable the system.

- **This software does not provide legal protection.** It is a technical tool, not a legal framework.

### 🧪 Testing vs Production

- **Always test thoroughly before arming.** Use `ADAPTER_MOCK_MODE=true` to prevent real notifications during testing.

- **Understand what will happen at each stage.** Use `python -m src.main explain-stages` to review all configured actions.

- **Start with long deadlines.** Give yourself ample time to understand the system before shortening intervals.

---

## Intended Use Cases

This software is designed for legitimate purposes including:

- **Personal continuity planning** — Ensuring loved ones receive important information
- **Journalistic protection** — Publishing materials if a journalist becomes unavailable
- **Business continuity** — Automated escalation for critical notifications
- **Scheduled publishing** — Time-delayed content release
- **Accountability systems** — Regular check-in requirements with escalation

---

## Prohibited Uses

You agree NOT to use this software for:

- **Harassment or threats** — Do not use this to threaten, coerce, or intimidate others
- **Illegal disclosure** — Do not publish content that violates laws or court orders
- **Extortion or blackmail** — This software must not be used as leverage for illegal demands
- **Circumventing legal processes** — Do not use this to evade lawful subpoenas or investigations
- **Harm to others** — Do not configure actions that could cause harm to individuals or organizations

---

## Your Responsibilities

By using this software, you acknowledge and accept:

1. **You are solely responsible** for all content configured for disclosure
2. **You understand the consequences** of all automated actions
3. **You have legal authority** to publish any configured content
4. **You will maintain your credentials** securely
5. **You will test thoroughly** before production use
6. **You accept all risks** associated with automated disclosure

---

## No Warranty

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.

IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

## Limitation of Liability

The authors and contributors of Continuity Orchestrator:

- **Do not guarantee** the software will function as expected in all circumstances
- **Are not responsible** for any disclosures made by the software, whether intentional or accidental
- **Do not provide** legal advice or protection
- **Cannot recover** information once disclosed
- **Are not liable** for any damages resulting from use or misuse of this software

---

## Acknowledgment

By using Continuity Orchestrator, you acknowledge that you have:

- [ ] Read and understood this disclaimer
- [ ] Reviewed the [Security Best Practices](SECURITY.md)
- [ ] Tested the system in mock mode before production use
- [ ] Configured appropriate safeguards (multiple renewal methods, trusted contacts)
- [ ] Accepted full responsibility for all configured actions

---

## Legal Jurisdiction

This software is provided as open-source under the MIT License. Users are responsible for ensuring their use complies with all applicable laws in their jurisdiction.

**If you do not agree to these terms, do not use this software.**

---

*Last updated: 2026-02-06*
