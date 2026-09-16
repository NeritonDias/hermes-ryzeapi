# Security

Never post secrets in issues, discussions, screenshots or pull requests. Account/instance tokens, QR/pairing codes, keys, databases and conversations do not belong in this repository.

Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/NeritonDias/hermes-ryzeapi/security/advisories/new). If unavailable, open only a request for private contact without exploitable details or sensitive data. This community beta does not promise a response SLA.

## Trust boundaries

- The plugin runs with Hermes permissions; it is not a sandbox.
- Dashboard authentication is required. Origin/CSRF checks do not replace login.
- Sending tools enforce recipient policies. They do not constrain every terminal/browser capability of the agent; enable minimal tools and use trusted groups.
- Allowing every group member to trigger the AI exposes its enabled tools. Messages and attachments must not change instructions or privileges.
- Status uses the WhatsApp audience, not the contact firewall, and requires specific authorization. PIX only displays a key; it does not transfer money.
- Credentials and state belong to the private profile, not the public plugin directory.
- The webhook checks its secret and scope; its listener binds to loopback. Publish only the required event route, never administrative endpoints.
- Uncertain POST requests are not automatically retried. Exactly-once delivery is not guaranteed.

## Data and retention

Private group archives are created after permitted activity and are not deleted automatically. Administrators are responsible for authorization, participant transparency and retention. Archives contain messages, available sender identifiers and membership changes, not complete copies of media attachments.

Media cache, queues, metrics and correlations have their own policies in the code. Operation records/receipts do not prove that a person received a message. Backups can also contain sensitive data; restrict their access.

Both skills are installed when the enabled plugin loads. Modified local copies are preserved; operators must resolve upgrade conflicts.

For setup instructions in Portuguese, see [Instalação e operação](docs/INSTALL.pt-BR.md).
