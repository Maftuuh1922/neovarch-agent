# Security Policy

## Supported versions

Security fixes are released for the latest release of Neovarch Agent only.
Please update to the [latest release](https://github.com/Maftuuh1922/neovrach_Agent/releases/latest) before reporting.

| Version | Supported |
| ------- | --------- |
| Latest release | ✅ |
| Older releases | ❌ |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately through GitHub:
**Security → Advisories → [Report a vulnerability](https://github.com/Maftuuh1922/neovrach_Agent/security/advisories/new)**.

Include:
- what is affected (desktop core, Android remote, pairing, or a tool),
- steps to reproduce, and
- the impact you expect.

We aim to reply within 7 days and to ship a fix as fast as the severity requires.
You will be credited in the release notes unless you prefer to stay anonymous.

## Scope

In scope:
- the desktop agent and its local data in `~/.neovarch`,
- phone ↔ PC pairing and the remote protocol,
- handling of API keys in `.env`,
- tools that run shell commands or touch files.

Out of scope: vulnerabilities in third-party model providers, and issues that need an already compromised PC.

## Good practice for users

- Keep API keys in `~/.neovarch/.env`; never commit them.
- Only pair phones you own, and re-pair if a phone is lost.
- Review shell and file permissions in Settings before enabling them.
