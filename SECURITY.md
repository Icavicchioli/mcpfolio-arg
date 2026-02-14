# Security Policy

## Supported Versions

Quant-Ollama is a local-first desktop tool with no versioned release guarantees yet. The `main` branch is always considered current. Security fixes are applied there.

## Reporting a Vulnerability

**Do not open a public GitHub Issue for security vulnerabilities.**

Report vulnerabilities by emailing the maintainer directly (contact visible in your fork/clone context) or by using [GitHub's private vulnerability reporting](https://github.com/your-username/quant-ollama-analyst/security/advisories/new) feature.

Please include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional but appreciated)

You can expect an acknowledgement within 72 hours and a resolution plan within 7 days for confirmed issues.

---

## Security Model

Quant-Ollama is designed as a **single-user local application**. Its security guarantees are scoped accordingly.

### What is protected

#### Portfolio data at rest
Portfolio holdings are encrypted before being written to disk.

**Scheme:**
```
user password
    │
    ▼ PBKDF2HMAC(algorithm=SHA-256, length=32, salt=random_16_bytes, iterations=390_000)
derived key (32 bytes)
    │
    ▼ Fernet(derived_key)
AES-128-CBC + HMAC-SHA256  →  base64url ciphertext
    │
    ▼
data/portfolio.enc
```

- The salt is stored alongside the ciphertext (standard PBKDF2 practice)
- The password is **never written to disk** in any form
- The session key is held in memory only while the portfolio is unlocked
- `390 000` PBKDF2 iterations exceeds OWASP's current minimum recommendation for SHA-256

#### LLM inference
All LLM calls go to a locally-running Ollama process. No prompt, ticker, or portfolio data is sent to any external AI service.

#### Market data
Ticker symbols are sent to Yahoo Finance via the yfinance library to fetch live prices. This is an inherent feature of the product — no workaround exists without a different data source. No account credentials or personally identifying information are transmitted.

### What is NOT protected

- **Network traffic**: The FastAPI server binds to `localhost` by default. If you expose port 8000 to a network (e.g., via `--host 0.0.0.0`), all API endpoints — including portfolio unlock — are accessible without authentication. Do not expose Quant-Ollama to untrusted networks.
- **Process memory**: The session key and decrypted portfolio are held in Python process memory while the portfolio is unlocked. Any process with sufficient privilege on the same machine can read them.
- **Ollama model weights**: LLM weights downloaded via `ollama pull` are stored unencrypted on disk under Ollama's default data directory. This is outside the scope of this project.
- **Log files**: `logs/quant-ollama.log` contains ticker symbols and analysis metadata but never portfolio holdings, prices, or passwords.

---

## Dependency Security

The CI pipeline runs two automated security scanners on every push:

| Tool | What it checks |
|---|---|
| [Safety](https://pypi.org/project/safety/) | Known CVEs in Python dependencies |
| [Bandit](https://bandit.readthedocs.io/) | Static analysis for common Python security anti-patterns |

Reports are uploaded as CI artifacts. Results are currently advisory (non-blocking) while the project matures.

Keep dependencies up to date. A Dependabot configuration (`.github/dependabot.yml`) automatically opens pull requests for outdated packages.

---

## Recommendations for Users

1. **Use a strong, unique password** for your portfolio — it is the only protection for your holdings data.
2. **Lock your portfolio** (`lock` button in the UI) when you walk away from the machine.
3. **Do not expose port 8000** to any network you do not fully trust.
4. **Keep Ollama updated** — model serving vulnerabilities are Ollama's responsibility, not this project's.
5. **Review model licenses** before using non-default models (e.g., Llama 3's Community License).
