# Secret and Credential Pattern Reference

## High-Risk Patterns (CRITICAL if found in source)

| Pattern | Regex hint | Example |
|---|---|---|
| AWS Access Key | `AKIA[0-9A-Z]{16}` | AKIAIOSFODNN7EXAMPLE |
| AWS Secret Key | 40-char base64 after `aws_secret` | — |
| GitHub Token | `ghp_[a-zA-Z0-9]{36}` | ghp_abc123... |
| GitHub App Token | `ghs_` or `ghu_` prefix | — |
| Stripe Secret Key | `sk_live_[a-zA-Z0-9]{24}` | — |
| Stripe Publishable | `pk_live_` | less sensitive |
| Private SSH Key | `-----BEGIN.*PRIVATE KEY-----` | in .env or .pem |
| Google API Key | `AIza[0-9A-Za-z\-_]{35}` | — |
| Slack Token | `xox[baprs]-` | — |
| Discord Bot Token | `[MNO][a-zA-Z0-9]{23}\.[a-zA-Z0-9-_]{6}\.[a-zA-Z0-9-_]{27}` | — |
| JWT | `eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+` | check alg=none |
| Generic password | `password\s*=\s*[^\s]+` | password=abc123 |

## Where to Scan
- `.env` files committed to git
- `backend/config.py`, `settings.py`
- `docker-compose.yml`, k8s secrets
- CI/CD workflow files (.github/workflows/*.yml)
- Jupyter notebooks (`.ipynb`) — tokens often left in cell outputs
- `package.json`, `requirements.txt` (dependency with embedded token)

## False Positive Reduction
- Entropy check: real secrets usually have Shannon entropy > 3.5
- Length check: most real tokens are 20+ chars
- Context check: `example`, `placeholder`, `your-key-here` are likely safe
- Skip `test_` or `mock_` prefixed variables in test files
