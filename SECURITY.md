# Security Policy

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

To report a vulnerability, use one of these channels:

- **GitHub private disclosure:** Use the [Security tab](https://github.com/TadMSTR/matrix-task-queue-bot/security/advisories/new) to submit a private advisory.
- **Email:** Send a description to `security.i9v75@8alias.com` with the subject line `[matrix-task-queue-bot] Security Report`.

Include as much detail as possible: the affected component, steps to reproduce, and potential impact.

## Scope

**In scope:**

- Authorization bypass allowing an unauthorized Matrix sender to trigger mutating actions
  (`!task start` / `!task approve`, or the `com.helmforge.task.start` / `.approve` widget events)
- Command or path injection via task IDs or command arguments into agent session launches
- Disclosure of task queue contents to senders outside the configured room
- Dependency vulnerabilities with a plausible exploitation path in the bot's usage

**Out of scope:**

- Vulnerabilities in the host system, the Matrix homeserver, or task-queue-mcp itself
- Issues requiring operator-level filesystem access to `~/.claude/task-queue/`
  (operator-controlled trust boundary, not an input attack surface)
- Theoretical weaknesses without a realistic attack path against the bot's command/event surface

## Response Expectations

| Stage | Timeline |
|-------|----------|
| Acknowledgement | Within 3 business days |
| Initial assessment | Within 7 business days |
| Fix or remediation plan | Within 30 days for critical/high; 60 days for medium/low |

This is a personal project maintained by one developer. Response times are best-effort.
If you haven't heard back within 3 business days, a follow-up email is welcome.

## Disclosure

Coordinated disclosure is preferred. Please allow time for a fix to be released before
public disclosure. The CHANGELOG documents remediated findings at an appropriate level
of detail after each release.
