# Security

MCPFolio is a single-user local application. It binds to `localhost` by default and is not designed for networked or multi-user deployment.

## Reporting a Vulnerability

Do not open a public GitHub Issue for security vulnerabilities.

Use [GitHub's private vulnerability reporting](https://github.com/adkarp/mcpfolio/security/advisories/new) or email the maintainer directly (contact visible in your fork/clone context).

Include a description of the vulnerability, steps to reproduce, and potential impact.

---

## Security Model

### What is protected

**Portfolio data at rest** — Holdings are encrypted before being written to disk.

```
password
    │
    ▼ PBKDF2HMAC(SHA-256, 390 000 iterations, random 16-byte salt)
derived key
    │
    ▼ Fernet (AES-128-CBC + HMAC-SHA256)
data/portfolio.enc
```

- The password is never written to disk in any form
- The session key lives in memory only while the portfolio is unlocked
- 390 000 PBKDF2 iterations exceeds OWASP's current minimum for SHA-256

**LLM inference** — All model calls go to a locally-running Ollama process. No prompt, ticker, or portfolio data is sent to any external AI service.

**Market data** — Only ticker symbols are sent to Yahoo Finance via yfinance. No account credentials or personally identifying information are transmitted.

### What is not protected

- **Network**: If you expose port 8000 beyond localhost (e.g. `--host 0.0.0.0`), all endpoints are accessible without authentication. Don't do this on untrusted networks.
- **Process memory**: The session key and decrypted portfolio are in Python process memory while the portfolio is unlocked.
- **Log files**: `logs/mcpfolio.log` contains ticker symbols and timing data, never holdings or passwords.

---

## Dependencies

The CI pipeline runs [Safety](https://pypi.org/project/safety/) (CVE scanning) and [Bandit](https://bandit.readthedocs.io/) (static security analysis) on every push. Reports are uploaded as CI artifacts. [Dependabot](/.github/dependabot.yml) opens PRs for outdated packages automatically.

---

## User Recommendations

1. Use a strong, unique password for your portfolio.
2. Lock the portfolio when stepping away from the machine.
3. Do not expose port 8000 to any network you don't fully trust.
