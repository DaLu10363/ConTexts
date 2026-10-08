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

## Stack

Python + Flask, server-rendered HTML, backed by SQLite. No build step, no JS
framework — minimal surface area for a single-user local tool.

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
flask --app app run --debug
```

Then open http://127.0.0.1:5000. The database and schema are created automatically on
first run. To wipe and reinitialize an existing database, run `flask --app app init-db`.

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
