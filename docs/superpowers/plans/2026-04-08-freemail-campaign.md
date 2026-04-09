# Freemail Campaign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a selectable freemail sending backend and optional rotating sender-address pool for campaign sends while preserving the existing SMTP path.

**Architecture:** Extend the sender layer with a freemail API transport and extend the campaign CLI with backend-selection and sender-pool parsing. Keep recipient loading and templates unchanged so the new behavior is isolated to mail transport and campaign configuration.

**Tech Stack:** Python 3, `python-dotenv`, `urllib.request`, `unittest`

---

### Task 1: Add regression tests for freemail config and sender-pool parsing

**Files:**
- Create: `tests/test_send_emails.py`
- Modify: `send_emails.py`

- [ ] **Step 1: Write the failing test**

```python
def test_load_freemail_config_reads_openreg_env():
    ...

def test_load_sender_pool_reads_itick_csv():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_send_emails -v`
Expected: FAIL because the helper functions do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def load_freemail_config(env_path: Path) -> dict:
    ...

def load_sender_pool(csv_path: Path) -> list[str]:
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_send_emails -v`
Expected: PASS

### Task 2: Add freemail sender transport

**Files:**
- Create: `tests/test_freemail_sender.py`
- Modify: `src/emailer/sender.py`

- [ ] **Step 1: Write the failing test**

```python
def test_freemail_sender_posts_api_request():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_freemail_sender -v`
Expected: FAIL because `FreemailSender` does not exist or lacks the expected behavior.

- [ ] **Step 3: Write minimal implementation**

```python
class FreemailSender:
    def send_email(...):
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_freemail_sender -v`
Expected: PASS

### Task 3: Wire backend selection into the campaign entrypoint

**Files:**
- Modify: `send_emails.py`
- Modify: `src/emailer/sender.py`
- Test: `tests/test_send_emails.py`

- [ ] **Step 1: Write the failing test**

```python
def test_sender_selection_uses_rotating_from_pool_for_freemail():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_send_emails -v`
Expected: FAIL because campaign sender selection does not support freemail rotation yet.

- [ ] **Step 3: Write minimal implementation**

```python
def build_campaign_sender(...):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_send_emails -v`
Expected: PASS

### Task 4: Verify the integrated CLI flow

**Files:**
- Modify: `send_emails.py`

- [ ] **Step 1: Run focused unit tests**

Run: `python -m unittest tests.test_send_emails tests.test_freemail_sender -v`
Expected: PASS

- [ ] **Step 2: Run CLI smoke check**

Run: `python send_emails.py --dry-run --max 2 --backend freemail --freemail-env /home/user/图片/openreg/.env --from-pool /home/user/图片/itick_autoreg/accounts/itick_latest.csv`
Expected: Dry-run output with freemail backend selected and no traceback.

- [ ] **Step 3: Review for backward compatibility**

Run: `python send_emails.py --dry-run --max 1`
Expected: Dry-run output using SMTP defaults and no traceback.
