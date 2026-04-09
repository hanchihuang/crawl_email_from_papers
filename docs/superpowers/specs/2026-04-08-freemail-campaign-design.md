# Freemail Campaign Sender Design

## Goal

Add a one-click bulk email flow that keeps the existing SMTP sender intact and adds a compatible `freemail` backend backed by the OpenReg worker API. The campaign still reads recipients from `data/authors/authors.json`.

## Current Context

- `send_emails.py` is the campaign entrypoint.
- `src/emailer/sender.py` contains SMTP sending and queue helpers.
- OpenReg already exposes a working outbound API at `FREEMAIL_API/api/send`.
- iTick account exports in `/home/user/图片/itick_autoreg/accounts/itick_latest.csv` provide candidate `from` addresses for rotation.

## Proposed Approaches

### Approach 1: Replace SMTP with freemail

Smallest code change, but it removes existing behavior and makes the project harder to reuse.

### Approach 2: Keep SMTP and add a selectable freemail backend

Recommended. It preserves current behavior, adds the requested temporary-mail sending path, and localizes the new logic to the sender layer plus CLI options.

### Approach 3: Shell out to `/home/user/图片/openreg/campaign_sender.py`

Fastest to hack together, but tightly couples this project to a separate script and makes verification and maintenance worse.

## Chosen Design

Use Approach 2.

## Architecture

- `send_emails.py` gains a `--backend smtp|freemail` option.
- `send_emails.py` loads freemail settings from `/home/user/图片/openreg/.env` by default when `--backend freemail` is selected.
- `src/emailer/sender.py` gains a `FreemailSender` class that calls `POST /api/send`.
- `send_emails.py` optionally loads a rotating sender-address pool from an iTick CSV passed by `--from-pool`.
- SMTP remains the default backend for backward compatibility.

## Data Flow

1. Load recipients from `authors.json`.
2. Choose backend from CLI.
3. If backend is `freemail`, load API configuration from the OpenReg `.env`.
4. If `--from-pool` is provided, parse the CSV first-column email addresses and rotate them across sends.
5. Render subject/body/html as before.
6. Send each message through the selected backend.

## Error Handling

- Fail early if freemail backend is selected without API URL or token.
- Fail early if `--from-pool` is provided but no valid sender addresses are found.
- Keep per-recipient send failures non-fatal so the campaign can continue.

## Testing

- Add unit tests for iTick sender-pool CSV parsing.
- Add unit tests for freemail env loading.
- Add unit tests for freemail request payload generation and authorization header handling.

## Constraints

- This workspace is not a git repository, so the spec cannot be committed here.
