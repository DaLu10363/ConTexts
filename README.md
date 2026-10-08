# ConTexts

A private, personal CRM for tracking business contacts, the context around past
discussions with them, and the ideas they're relevant to. Unlike LinkedIn, nothing
here is shared — it's a private memory layer for your own network.

## Data model

- **Contacts** — people you know: name, company, title, contact info, bio.
- **Companies** — the organizations your contacts work at: name, website,
  industry/sector (picked from a fixed list, also proposed by Claude via
  "Fill gaps with Claude"), description. Scored against Nodes the same way
  contacts are.
- **Nodes** — role classifications a contact can qualify for (e.g. Investor,
  Supplier, Cofounder, Consultant, Contributor/Contractor). Each contact gets a
  0-100 compatibility score per node, so one person can score well as both a
  "Consultant" and an "Investor", for example.
- **Interactions** — timestamped notes logged after a call or meeting with a
  contact (what was discussed, next steps). These roll up into that contact's
  profile as a timeline.
- **Ideas** — business or project ideas, linked to the contacts relevant to
  pursuing them.
- **Briefings** — meeting/communication prep, parallel to the rest of the
  database. You pick a contact and describe the purpose of an upcoming
  communication; Claude researches them (your logged history plus a web
  search on them and their company) and drafts a reviewable briefing. After
  the communication happens, you log what came up and Claude turns it into a
  logged interaction, folding anything company-level into the company record.

## Dashboard

The landing page (`/`) has clickable counts for Contacts, Companies, Ideas,
and Briefings (jumps to that list), plus a **relationship graph**: your Nodes
as hub points, with Contacts and Companies connected to whichever Nodes
they're scored against — a closer/shorter edge means a better fit, and a
thicker edge connects a contact to the company they currently work at. Points
are colored by type (Node / Company / Contact), hover shows the name, and
clicking a point opens it (clicking a Node jumps to the contacts list
filtered to that node). Built with D3's force simulation; no data ever
leaves the browser for this view — it's rendered entirely from your own
database.

## Briefings

A briefing is prep for an upcoming call or meeting with a contact, tracked
alongside the rest of the database (the `Briefings` tab).

1. **Create one** — pick the contact (and optionally an Idea it relates to),
   and state the purpose, format, and date. Claude researches them (your
   logged history plus a live web search on them and their company) and
   drafts a summary, contact/company highlights, talking points, and open
   questions — all editable on the review screen before saving.
2. **Checklist** — on the briefing's page, before logging the outcome, build
   a checklist of concrete, checkable items to work through: click "Suggest
   checklist with Claude" to propose a few grounded in that specific
   briefing (purpose, talking points, open questions), or add your own.
   Check items off as you go, or remove any that don't apply.
3. **Log the outcome** — once the communication happens, describe what came
   up; checked checklist items are already pulled into the notes as a
   starting point, so you're editing/adding rather than starting blank.
   Claude turns this into a logged interaction on the contact and, only
   where it's actually relevant, proposes an updated company description
   (e.g. a funding program's deadline they mentioned) — reviewable before
   saving. The briefing is then marked completed.

## LLM-assisted classification

Two optional, Claude-assisted flows feed the judgment signal used to score
contacts against nodes:

- **LinkedIn profile parsing** — paste a contact's LinkedIn profile text (copy
  it manually from the page) into the "New contact" form, click "Parse with
  Claude", and review the extracted work history, education, and skills before
  saving. There is no LinkedIn API for pulling a third party's profile data, so
  this is a manual copy/paste step — Claude only structures what you've already
  pasted. In the same call, Claude also suggests node compatibility scores
  based on the profile, and lists the companies found in the work history so
  you can add them to the companies list and link the current employer — all
  reviewable/editable on the same confirmation screen before anything saves.
- **Interaction analysis** — when you log an interaction, you tag whether the
  note is a verbatim copy (e.g. from an email) or recalled from memory, then
  Claude proposes topic tags, a tone descriptor, and a short rationale. You
  review and can edit before it's saved.

(Briefings also call Claude — for research, the checklist, and outcome
analysis — covered above.)

All of these calls go through the Anthropic API server-side (see `llm.py`);
nothing is written to the database until you confirm the review screen.

Each contact, company, and idea page has a single **"Fill gaps with Claude"**
button rather than separate buttons per feature — it picks up whatever is new
(a logged interaction, a newly linked company, an edited description, ...)
and refreshes the relevant scores in one pass. For companies specifically,
this button also runs live web research. Claude never guesses which
same-named company you mean from the name alone, so if there's no website on
file yet, clicking the button doesn't call Claude at all — it first asks you
for the website, then researches and scores together using that, so the
score suggestions are grounded in the real company rather than a thin or
wrong guess.

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

## Version history

The current version is shown at the bottom of every page.

- **v0.1** — First publication. Contacts, Companies, Nodes, Ideas, and
  Briefings, with Claude-assisted LinkedIn parsing/scoring, interaction
  analysis, company research, and meeting briefings (each behind a
  review-before-save screen); a dashboard with a D3 relationship graph;
  a light/dark (blue-violet) theme with a manual toggle; and breadcrumb
  navigation.
