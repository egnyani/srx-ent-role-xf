# Apply Agent Setup

This repo now includes the first layer for a future application agent:

- a persistent application queue at `data/apply_queue.json`
- a profile template at `data/applicant_profile.template.json`
- queue-building scripts under `scripts/`

## Current Scope

Greenhouse can now be filled and submitted with success-page verification.

It prepares the data model needed for a supervised apply agent later, whether that is built with:

- Playwright
- Clawbot
- another local desktop-control tool

## Files

- `data/applicant_profile.template.json`
  - your reusable application answers and document paths
- `data/apply_queue.json`
  - queued jobs to work through
- `scripts/build_apply_queue.py`
  - builds queue items from `output/entry_roles.xlsx`
- `scripts/queue_summary.py`
  - shows queue counts and auto-apply readiness
- `scripts/run_greenhouse_apply.py`
  - prepares a supervised Greenhouse application session
- `scripts/fill_greenhouse_form.py`
  - opens a real browser, fills saved answers, and can optionally submit
- `scripts/extract_greenhouse_fields.py`
  - extracts live Greenhouse fields from the rendered page into `output/live_field_plans/`
- `scripts/plan_greenhouse_answers.py`
  - builds a live answer plan from extracted fields using profile + memory + LLM fallback

## Build The Queue

Strict jobs only:

```bash
python scripts/build_apply_queue.py
```

Include interesting jobs too:

```bash
python scripts/build_apply_queue.py --include-interesting
```

Limit the number of newly queued jobs:

```bash
python scripts/build_apply_queue.py --limit 50
```

## Queue Model

Each queue item stores:

- company
- title
- location
- source URL
- strict vs interesting bucket
- queue status
- inferred application target
- whether the job is in the first auto-apply scope

Queue states currently used:

- `queued`
- `in_progress`
- `filled_for_review`
- `needs_manual_review`
- `needs_email_code`
- `submitted`
- `failed`

Initial auto-apply scope:

- Greenhouse
- Lever

Everything else stays queueable, but should be treated as manual or later-phase automation.

## Recommended Next Build Step

Start with a supervised local agent that:

1. picks the next `queued` item with `auto_apply_supported=true`
2. opens the application in a real browser
3. fills known fields from your profile
4. pauses for custom questions
5. submits only after review

The first runnable apply step is now:

```bash
python scripts/run_greenhouse_apply.py
python scripts/fill_greenhouse_form.py
```

That command:

- selects the next queued Greenhouse job
- fetches the live Greenhouse application form
- maps saved profile answers to known fields
- writes a session file under `output/apply_sessions/`
- updates the queue item to `in_progress`
- opens the live job page in a browser unless `--no-open` is passed

The second step is:

```bash
python scripts/fill_greenhouse_form.py
```

That command uses Playwright Python, fills the saved answers into the live Greenhouse form, and leaves the browser open for review.

To submit after filling:

```bash
python scripts/fill_greenhouse_form.py --submit
```

The submit path marks a job `submitted` if the submit click succeeds and Greenhouse does not show an email-code checkpoint or inline validation errors immediately after. If the site asks for verification, the queue item moves to `needs_email_code`. If Greenhouse still shows validation errors after submit, it moves to `failed`.

## Live Planning Flow

The scalable path for high-volume applications is:

```bash
python scripts/run_greenhouse_apply.py --no-open
.venv/bin/python scripts/extract_greenhouse_fields.py --session output/apply_sessions/<session>.json
python scripts/plan_greenhouse_answers.py --session output/apply_sessions/<session>.json
.venv/bin/python scripts/fill_greenhouse_form.py --session output/apply_sessions/<session>.json
```

This separates:

- `extract`
- `plan`
- `apply`
- `verify`

The generated artifacts live under:

- `output/live_field_plans/`
- `output/question_debug/`
- `data/answer_memory.json`

After the fill step:

- clean fills move to `filled_for_review`
- partial fills move to `needs_manual_review`
- verified submissions move to `submitted`
- email verification checkpoints move to `needs_email_code`

## Information We Will Need From You Later

When we start the actual apply flow, we will need values for:

- full name
- email
- phone
- city/state
- LinkedIn/GitHub/portfolio
- school / degree / major / graduation date
- resume file path
- sponsorship answer
- relocation preference
- salary expectation default

Keep secrets and credentials out of the repo. Use local environment variables, OS keychain storage, or a local secret manager when we reach the browser automation phase.

## Instruction Notes

Your applicant profile can also store application-specific defaults and guardrails, for example:

- visa status such as `F1 OPT`
- relocation default answer
- sponsorship wording
- Workday-specific cleanup notes
- preferred city/state override for application forms

These are stored in `data/applicant_profile.template.json` so the future apply runner can use them consistently instead of relying on ad hoc prompts.

## Optional AI Fallback (Groq or Ollama)

The Greenhouse runner can optionally ask an LLM for suggestions when a field is still unresolved after profile mapping.

**Recommended: Groq (free tier, Llama 3.3 70B)**

1. Sign up at [console.groq.com](https://console.groq.com)
2. Create an API key
3. Add to `.env`: `GROQ_API_KEY=your_key_here`
4. In `data/applicant_profile.template.json`, set:
   ```json
   "ai_fallback": {
     "enabled": true,
     "provider": "groq",
     "model": "llama-3.3-70b-versatile"
   }
   ```

**Alternative: Ollama (local)**

- provider: `ollama`
- model: `llama3.1:8b`
- endpoint: `http://127.0.0.1:11434/api/generate` (or `OLLAMA_API_URL` env)

This is only a fallback. The runner prefers explicit profile answers first and uses domain-specific rules for EEO, phone, and education fields before calling the LLM.
