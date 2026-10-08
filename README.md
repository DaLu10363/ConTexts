# ConTexts

A private, personal CRM for tracking business contacts, the context around past
discussions with them, and the ideas they're relevant to. Unlike LinkedIn, nothing
here is shared — it's a private memory layer for your own network.

## Data model

- **Contacts** — people you know: name, company, title, contact info, bio.
- **Nodes** — role classifications a contact can qualify for (e.g. Investor,
  Supplier, Cofounder, Consultant, Contributor/Contractor). Each contact gets a
  0-100 compatibility score per node, so one person can score well as both a
  "Consultant" and an "Investor", for example.
- **Interactions** — timestamped notes logged after a call or meeting with a
  contact (what was discussed, next steps). These roll up into that contact's
  profile as a timeline.
- **Ideas** — business or project ideas, linked to the contacts relevant to
  pursuing them.

## LLM-assisted classification

Two optional, Claude-assisted flows feed the judgment signal used to score
contacts against nodes:

- **LinkedIn profile parsing** — paste a contact's LinkedIn profile text (copy
  it manually from the page) into the "New contact" form, click "Parse with
  Claude", and review the extracted work history, education, and skills before
  saving. There is no LinkedIn API for pulling a third party's profile data, so
  this is a manual copy/paste step — Claude only structures what you've already
  pasted.
- **Interaction analysis** — when you log an interaction, you tag whether the
  note is a verbatim copy (e.g. from an email) or recalled from memory, then
  Claude proposes topic tags, a tone descriptor, and a short rationale. You
  review and can edit before it's saved.

Both calls go through the Anthropic API server-side (see `llm.py`); nothing is
written to the database until you confirm the review screen.

## Stack

Python + Flask, server-rendered HTML, backed by SQLite. No build step, no JS
framework — minimal surface area for a single-user local tool.

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000. The database and schema are created automatically on
first run. To wipe and reinitialize an existing database, run `flask --app app init-db`.

**Use `python app.py`, not `flask run`.** On this machine, `flask --app app run`
defers importing the app until the first HTTP request arrives, and that lazy
import has intermittently failed (seemingly from OneDrive still syncing files
inside a freshly-created `.venv`), permanently caching a "No module named
'anthropic'" error for that process's lifetime even after the underlying issue
clears. Running `python app.py` imports everything immediately and synchronously
at startup, so a failure shows up right away in the terminal instead of as a
silent, sometimes-works 500 later.

**If you ever see an Internal Server Error that doesn't match the code:**
check Task Manager for leftover `python.exe` processes before debugging
further. Windows allows multiple processes to bind the same port
simultaneously (`SO_REUSEADDR` behaves differently than on Linux), so an old,
un-killed server from a previous run can keep answering requests on port 5000
alongside — or instead of — the one you just started, serving stale or broken
behavior. Always stop the previous server (Ctrl+C, and confirm the process
actually exited) before starting a new one.

## Database location

The SQLite file defaults to `instance/contexts.db`, which is git-ignored.

**This project folder lives in OneDrive.** Running a live SQLite database inside
a synced folder risks file-lock errors or corruption if OneDrive tries to sync
the `.db` file mid-write. To avoid that, point the database somewhere outside
OneDrive via an environment variable, e.g.:

```
setx CONTEXTS_DB "%LOCALAPPDATA%\ConTexts\contexts.db"
```

Set it before running `flask ... init-db` / `flask ... run` so both use the same
path. The code (this repo) stays synced and versioned; the data stays local and
untouched by OneDrive.

## Anthropic API key

The LinkedIn-parsing and interaction-analysis features call the Anthropic API
server-side. Set your key as a Windows environment variable — **not** in any
file in this folder, and never paste it into chat:

```
setx ANTHROPIC_API_KEY "sk-ant-your-real-key-here"
```

Open a new terminal after running this (environment variables set with `setx`
only apply to new terminal sessions) before starting the app. The key is read
once per process by `anthropic.Anthropic()` in `llm.py` and is never sent to
the browser, stored in the database, or rendered into any page.

## Your data never goes to GitHub

`.gitignore` excludes `instance/` and `*.db`, so the SQLite database — your actual
contacts, interaction notes, node scores, and ideas — is never committed and never
pushed, regardless of the database's location or whether this repo is public or
private. Only the application code (this repo's tracked files) goes to GitHub.
Before ever making the repo public, you can double check no database file was ever
committed by accident with:

```
git log --all --full-history -- '*.db'
```

An empty result confirms none exists in history.
