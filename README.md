# ConTexts

A small, private, single-user notebook for business contacts — and the context that came with them.

**Status:** v0.1. An MVP built in an afternoon to solve one person's problem. Not a product, not a CRM, not operational software.

---

## Why this exists

I left a networking event with eleven business cards, four voice memos and one genuinely good conversation I'd had in a car park. Three weeks later I could not remember which card belonged to the car park.

LinkedIn is very good at telling me *that* I know someone. It is useless at telling me *how* — who introduced us, what we agreed, and whether this person was a potential co-founder, an investor, a supplier, or someone who wanted to sell me insurance.

A contact without context is just a name. Hence the pun, and hence this repo.

Commercial CRMs solve a different problem: they are built around sales pipelines, they cost money, and they want your contacts on their servers. I wanted notes on my own disk. So I built this instead.

## What it is

- A local SQLite database and a server-rendered Flask UI, running on `127.0.0.1`.
- Somewhere to record **who you met, how, and what came of it**.
- A way to prepare for the next meeting without re-reading six months of email.

## What it is not

- Not multi-user. There are no accounts, no permissions, no sharing.
- Not hardened. There is no authentication, because it is expected to run only on your own machine.
- Not designed. The UI was built by an engineer in a hurry and looks like it.
- Not a CRM, and not a replacement for one if you actually run a sales team.

If any of that is a problem for your use case, fork it — that's what the licence is for.

---

## Data model

- **Contacts** — people you know: name, company, title, contact info, bio.
- **Companies** — the organizations your contacts work at: name, website,
  industry/sector (picked from a fixed list, also proposed by Claude via
  "Fill gaps with Claude"), description, and optionally a parsed LinkedIn
  company page. Scored against Nodes the same way contacts are.
- **Nodes** — role classifications a contact or company can qualify for (e.g.
  Investor, Supplier, Cofounder, Consultant, Contributor/Contractor). Each one
  gets a 0-100 compatibility score per node, so one person can score well as
  both a "Consultant" and an "Investor", for example.
- **Interactions** — timestamped notes logged after a call or meeting (what
  was discussed, next steps) — either with a contact, or with a company as a
  whole when there was no single person (a team call, a shared inbox, a
  formal letter). A company's timeline shows its own interactions plus those
  with its contacts.
- **Ideas** — business or project ideas, linked to the contacts and companies
  relevant to pursuing them.
- **Briefings** — meeting/communication prep, parallel to the rest of the
  database. You pick a contact or a company and describe the purpose of an
  upcoming communication; Claude researches them (your logged history plus a
  web search) and drafts a reviewable briefing. After the communication
  happens, you log what came up and Claude turns it into a logged
  interaction, folding anything company-level into the company record.

Contact and company pages share one layout: facts and bio first, then linked
ideas, node compatibility, meeting briefings, interaction history, and the
parsed LinkedIn profile at the bottom. Logging an interaction and linking a
company (or, on a company, a contact) live on a separate page behind the
**Log interaction / Link …** button at the top, next to **Fill gaps with
Claude**.

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

A briefing is prep for an upcoming call or meeting with a contact — or with
a company as a whole — tracked alongside the rest of the database (the
`Briefings` tab).

1. **Create one** — pick the contact or company (and optionally an Idea it
   relates to), and state the purpose, format, and date. Claude researches
   them (your logged history plus a live web search) and drafts a summary,
   contact/company highlights (for a company briefing: its key people),
   talking points, and open questions — all editable on the review screen
   before saving.
2. **Checklist** — on the briefing's page, before logging the outcome, build
   a checklist of concrete, checkable items to work through: click "Suggest
   checklist with Claude" to propose a few grounded in that specific
   briefing (purpose, talking points, open questions), or add your own.
   Check items off as you go, or remove any that don't apply.
3. **Log the outcome** — once the communication happens, describe what came
   up; checked checklist items are already pulled into the notes as a
   starting point, so you're editing/adding rather than starting blank.
   Claude turns this into a logged interaction on the contact (or company)
   and, only
   where it's actually relevant, proposes an updated company description
   (e.g. a funding program's deadline they mentioned) — reviewable before
   saving. The briefing is then marked completed.

## LLM-assisted classification

All model calls are made server-side from `llm.py`, and every result is shown to you for review before anything is written to the database.

- **Profile text parsing** — paste the text of a person's or a company's LinkedIn page that you have copied yourself, and the app structures it into fields. It does not connect to LinkedIn or any other site, log in anywhere, or fetch anything. It parses text you give it, nothing more.
- **Interaction analysis** — suggests topic tags and a tone read for a note you've written. Optional: if the model is unavailable, you fill these in yourself and save anyway.
- **Fill gaps with Claude** — a button at the top of each contact, company and idea page. It proposes node scores for a contact or company, and per-contact fit scores for an idea.
- **Company research** — part of a company's "Fill gaps", and it waits until the company has a website before calling the model, so it never guesses between same-named companies.

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

**I run this project folder in OneDrive.** Running a live SQLite database inside
a synced folder risks file-lock errors or corruption if OneDrive tries to sync
the `.db` file mid-write. To avoid that, point the database somewhere outside
OneDrive via an environment variable, e.g.:

```
setx CONTEXTS_DB "%LOCALAPPDATA%\ConTexts\contexts.db"
```

Open a new terminal after `setx` so the variable is picked up. Set it before
running `flask --app app init-db` / `python app.py` so both use the same
path. The code (this repo) stays synced and versioned; the data stays local and
untouched by OneDrive.

## Anthropic API key

The LLM features need an API key, read from the environment by `anthropic.Anthropic()` in `llm.py`.

Windows:

```
setx ANTHROPIC_API_KEY "sk-ant-your-real-key-here"
```

macOS / Linux:

```
export ANTHROPIC_API_KEY="sk-ant-your-real-key-here"
```

Open a new terminal after `setx` so the variable is picked up.

The key is never sent to the browser, stored in the database, or rendered into any page.

Put it in your environment, never in a project file. Model calls cost money against your own account; the app does not meter or cap that, so keep an eye on usage.

The rest of the app works without a key — you lose briefings, profile parsing, company research and the fill-gap suggestions, and interaction notes are saved without suggested tags.

## Your data never goes to GitHub

`.gitignore` excludes `instance/` and `*.db`, so the database is not committed. To check that none was ever committed by accident (an empty result means none):

```
git log --all --full-history -- '*.db'
```

Note that the LLM features do send the text you submit — contact details, your notes — to the Anthropic API for processing. If that isn't acceptable for a particular contact, don't use those buttons for that record.

## Your data, your responsibility

This app stores notes about identifiable people, and in the EU that makes whoever runs it the controller of that data. If you use ConTexts for anything beyond your own private notes, that's your call and your obligation: keep the database on a device you control, store only what you actually need, write notes you would be comfortable showing the person they're about, and delete records when you no longer have a reason to keep them.

The author ships no telemetry and receives none of your data. Everything stays in your SQLite file unless you press one of the LLM buttons.

## Licence

MIT. Copyright (c) 2026 DaLu10363. Do what you like with it; no warranty of any kind.

## Version history

The current version is shown at the bottom of every page.

- **v0.1** — first publication.