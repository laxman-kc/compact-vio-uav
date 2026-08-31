# Security policy

## Supported surface

| Surface | Status |
|---|---|
| Current `main` branch | Supported on a best-effort research basis |
| Older commits or local forks | Not supported |
| Hosted service or public inference API | None exists |
| Physical-flight or control integration | Not supported |

There is no production service, hosted inference endpoint, or security response-time guarantee.

## Report a vulnerability privately

Do not include private recordings, credentials, model artifacts, or working exploit payloads in a
public issue. Prefer GitHub's
[private vulnerability report](https://github.com/laxman-kc/compact-vio-uav/security/advisories/new).
If that feature is unavailable, contact the repository owner privately through the account that
hosts this repository.

Include only the minimum non-sensitive information needed to reproduce the issue:

- the affected command, module, and Git commit;
- a synthetic or otherwise non-sensitive reproduction;
- the expected and observed behavior;
- the potential impact;
- any temporary mitigation you found.

The maintainer will acknowledge and coordinate disclosure on a best-effort basis. Please do not
publish exploit details before a fix or mitigation can be evaluated.

## Security-sensitive boundaries

Recording ZIPs and model packages are untrusted input. In particular, please report any bypass
that can:

- write outside the temporary extraction directory;
- evade path, duplicate, symbolic-link, encryption, member-count, or expansion limits;
- cause malformed calibration, timestamp, IMU, or model metadata to appear verified;
- load a model artifact whose declared hashes or package relationships do not match;
- expose local recordings, credentials, or machine-local paths in generated reports.

The application is intended to process recordings locally. The demo restricts its listener to a
loopback address and disables Gradio share links. Any future hosted or shared deployment requires
a separate security review.
