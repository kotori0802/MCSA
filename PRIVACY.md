# Privacy Policy

**Mouse Click Stability Analyzer (MCSA)**  
Last updated: 2026-09-01  
Author: Leo Cheng, PMP

This policy describes how MCSA handles information on **your computer**. MCSA is distributed as source code; you run it locally. There is no MCSA-operated cloud backend in v1.

## Summary

| Question | Answer |
| -------- | ------ |
| Does MCSA send data to the internet? | **No** (v1 default) |
| Does MCSA read passwords or keyboard input? | **No** |
| Where is data stored? | Locally under `reports/` (configurable) |
| Who can see my reports? | Only people/processes with access to your PC |

## Data collected locally

When you run a test and generate a report, MCSA may write:

### Click session data

- Timestamps, button (Left/Right/etc.), hold time, intervals
- Classification tags (chatter, miss, extra click, etc.)
- Optional operator name and device label **you type in**

### Host test environment (in reports)

- Windows platform string (e.g. `Windows-10-10.0.26200`)
- Python version
- Capture backend name
- Test settings (Hz, duration, profile)
- **Future (Phase 1C):** optional USB HID device VID/PID / instance id when you scan and bind a mouse

### Not collected

- Windows username (not auto-filled)
- Files outside reports folder
- Network traffic, clipboard, screenshots, keystrokes
- Account passwords or browser credentials

## Compare overlay

Loading a previous run reads a **local JSON file** you select. That file stays on your machine; MCSA does not upload it.

## Your responsibilities

- **Do not** commit real `reports/` to public GitHub — they may identify test hardware or internal hostnames.
- Redact operator names and device labels before sharing reports externally.
- If you fork MCSA and add cloud/LLM features, disclose that clearly to your users.

## Future: optional LLM narrative (planned v2)

If enabled in a future version:

- Sending report excerpts to an LLM API would be **opt-in only**
- UI would list exactly which fields are transmitted
- Deterministic JSON/CSV summaries would remain the audit source of truth

No LLM feature ships in v1.

## Children’s privacy

MCSA is a professional QA tool, not directed at children under 13.

## Changes

Material changes to this policy will be noted in the repository changelog / release notes.

## Contact

Privacy questions: use the contact method listed on the GitHub repository profile or open a **non-sensitive** discussion issue.
