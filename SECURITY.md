# Security Policy

**Mouse Click Stability Analyzer (MCSA)** is an independent portfolio project maintained by Leo Cheng.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.0.x   | Yes       |

## Reporting a vulnerability

Please **do not open a public GitHub issue** for security vulnerabilities or include sensitive technical details in public discussions.

1. Use [GitHub private vulnerability reporting](https://github.com/kotori0802/mouse-click-stability-analyzer/security/advisories/new) if it is enabled for this repository.
2. If private vulnerability reporting is unavailable, use a professional contact method listed on the maintainer's GitHub profile, if one is provided.

When reporting a vulnerability, please include:

- Affected version
- Steps to reproduce
- Expected and observed behavior
- Potential impact on confidentiality, integrity, or availability
- Proof-of-concept or sample input, if appropriate
- Any suggested mitigation, if available

Please avoid including real device identifiers, internal hostnames, confidential test data, passwords, access tokens, or other sensitive information unless it is necessary to understand the issue.

We aim to acknowledge valid vulnerability reports within **7 business days**. Fixes and mitigations are prioritized based on severity, reproducibility, and potential impact.

## Scope

### In scope

- Python source code in this repository
- Launch and installation scripts, including `run.bat` and `install.bat`
- Bundled Windows Raw Input adapters
- Local report generation under `reports/`
- Compare Overlay JSON loading, including file-size limits and parser behavior
- Windows Raw Input subprocess communication:
  - `raw_input_subprocess.py`
  - `raw_input_bridge.py`

### Out of scope

- Vulnerabilities caused by a compromised or unsupported host operating system
- Third-party Python installations or packages modified outside this repository
- Malware or modified binaries falsely presented as official MCSA releases
- Social-engineering attempts or phishing
- Vulnerabilities originating directly from Python, PySide6, Windows, or other third-party dependencies; these should also be reported to the relevant upstream project

## Security model

MCSA is designed as a **local, offline QA utility**.

By design, MCSA:

- Does **not** upload test reports or host information to a cloud service
- Does **not** record or persist typed keyboard content, passwords, browser data, or unrelated user files
- May handle designated control keys, such as **F5** and **Esc**, locally for test-session control
- Does **not** require administrator privileges for normal operation
- Does **not** execute remote code
- Does **not** automatically download or install updates from untrusted URLs

MCSA **does** capture mouse-button timing through Windows Raw Input.

Reports generated locally may also contain limited environment metadata, such as:

- Operating-system platform information
- Python version
- Optional device VID/PID information when device scanning is enabled
- Test configuration and timing data

Users should review generated reports before sharing them outside their own environment.

## Data and privacy considerations

Runtime reports are stored locally under `reports/`.

The public GitHub repository is configured so that real test sessions are not tracked by Git. Only `reports/.gitkeep` is intended to remain in version control.

Generated reports may contain information that should not be published, including:

- Device identifiers
- VID/PID values
- Hostnames
- Local environment information
- Test timestamps
- User-entered DUT or operator labels

Do not commit real reports to public repositories unless the data has been reviewed and intentionally sanitized.

See [`PRIVACY.md`](PRIVACY.md) for additional information about local data handling.

## Hardening notes for users

- Download MCSA only from the official repository or releases you trust.
- Verify release checksums when checksums are provided.
- Do not commit the contents of `reports/` to a public repository without reviewing and sanitizing the data first.
- When using **Compare Overlay**, load only `*_detail.json` files created by you or received from a trusted source.
- Overlay files are limited to approximately **32 MiB / 150,000 events** to reduce the risk of excessive memory use from unexpectedly large or malicious JSON input.
- Run MCSA with normal user privileges unless a specific troubleshooting scenario requires otherwise.

## Maintainer practices

The project follows these development practices:

- Dependencies are declared in `pyproject.toml`, including optional extras such as `gui` and `excel`
- No use of `eval()` or `pickle` for untrusted Compare Overlay input
- Runtime reports are excluded from Git version control
- Public examples use synthetic or intentionally sanitized data
- Changes should be reviewed before merging into `main`
- Security-sensitive changes should be tested using local or synthetic data before release

Recommended or planned automated checks may include:

- `pip-audit`
- `bandit`
- GitHub Dependabot
- GitHub CodeQL or other static-analysis tools when appropriate

These automated checks may not be enabled for every release and should not be treated as a replacement for manual review.

## Responsible disclosure

This project follows coordinated disclosure when practical.

Please allow reasonable time to investigate and address a reported vulnerability before publishing technical details.

Security contributors may be credited in release notes unless they request anonymity.
