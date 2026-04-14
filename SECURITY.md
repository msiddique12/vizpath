# Security Policy

## Reporting a vulnerability

If you discover a security issue, report it privately and do not disclose it publicly until we’ve had a chance to review and fix it.

Please include:

- A clear description of the issue
- Affected versions
- Reproduction steps (or PoC)
- Any logs or screenshots
- Contact method for follow-up

Email: [security@vizpath.example.com](mailto:security@vizpath.example.com)

If no dedicated security inbox is available, use a GitHub private report through Security Advisories.

## Supported versions

We currently maintain fixes for the `main` branch and the latest minor release stream. If you are using an older snapshot, we recommend upgrading.

## Response expectations

We aim to acknowledge valid reports quickly and work toward a fix with reasonable urgency based on impact.

## Safe handling

- Avoid sharing secrets, API keys, or customer data when reporting.
- For remote debugging, provide sanitized test cases only.

## Automated security checks

The repository runs a dedicated `Security` GitHub Actions workflow with:

- Secret scanning (`gitleaks`) on pushes and pull requests
- Python dependency auditing (`pip-audit`) for `server` and `sdk`
- Dashboard production dependency auditing (`npm audit --omit=dev --audit-level=high`)

Local equivalents:

```bash
# Secret scan
gitleaks detect --source . --redact

# Python dependency audits
pip install pip-audit
pip install -e "./server[dev]"
pip-audit
pip install -e "./sdk[dev]"
pip-audit

# Dashboard prod dependency audit
cd dashboard && npm ci && npm audit --omit=dev --audit-level=high
```
