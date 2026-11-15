# Security policy

## Reporting a vulnerability

Report it privately through GitHub's **private vulnerability reporting**: on the repository,
open *Security* → *Report a vulnerability*. Do not open a public issue, pull request or
discussion for a suspected vulnerability.

Please include the affected version (`heracles --version` or the image tag), the
configuration involved, steps to reproduce and the impact you see. You may use any language
you are comfortable with.

## What to expect

| Step | Target |
| --- | --- |
| Acknowledgement | 3 working days |
| First assessment (severity, affected versions) | 10 working days |
| Fix for a critical or high severity issue | 30 days |
| Fix for a medium or low severity issue | next minor release |

We coordinate the disclosure date with you, publish a GitHub security advisory with a CVE when
one applies, and credit you unless you prefer otherwise.

## Supported versions

While Heracles is below 1.0, only the **latest minor release** receives security fixes. From
1.0 on, the latest minor release and the previous one do, as described in the
[versioning policy](manual/versioning.md#support).

## Scope

In scope: the Heracles server, worker, CLI, web console and self-service portal, the published
container images and Helm chart. Out of scope: the directory server, mail server, PostgreSQL and
other software Heracles talks to (report those to their maintainers), and findings that need an
already compromised administrator account.
