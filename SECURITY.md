# Security Policy

## Scope

This project fetches data from public government APIs (FRED, BLS, Treasury, FDIC). It stores computed signals in a local SQLite database on the user's machine. It does not collect, transmit, or store any personal data.

## API Keys

- FRED API keys are stored locally by Claude Desktop and passed as environment variables. They are never committed to the repository or transmitted to any third party.
- The `.gitignore` excludes `.env` files to prevent accidental key exposure.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public issue
2. Email **support@mcpbundles.com** with details
3. We will acknowledge within 48 hours and work on a fix

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |
