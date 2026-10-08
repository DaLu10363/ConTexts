import json
import math
import os
import sqlite3
from datetime import date
from pathlib import Path

from flask import Flask, abort, g, redirect, render_template, request, url_for

import llm

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "instance" / "contexts.db"
DB_PATH = Path(os.environ.get("CONTEXTS_DB", DEFAULT_DB_PATH))

app = Flask(__name__)
app.add_template_filter(json.loads, name="from_json")


def _freshness(last_contact_str):
    """Logarithmic recency score from a date/datetime string - purely a
    visual freshness indicator, never an input to node scoring math."""
    if not last_contact_str:
        return None
    try:
        last_date = date.fromisoformat(last_contact_str[:10])
    except ValueError:
        return None
    days = max((date.today() - last_date).days, 0)
    heat = 1 / (1 + math.log10(1 + days))
    if days <= 14:
        label, css_class = "Hot", "heat-hot"
    elif days <= 90:
        label, css_class = "Warm", "heat-warm"
    elif days <= 365:
        label, css_class = "Cooling", "heat-cooling"
    else:
        label, css_class = "Cold", "heat-cold"
    return {
        "date": last_date.isoformat(),
        "days": days,
        "heat": round(heat, 3),
        "label": label,
        "css_class": css_class,
    }


def ensure_schema(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS companies ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
        "description TEXT, website TEXT, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS company_nodes ("
        "company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE, "
        "node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE, "
        "score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100), notes TEXT, "
        "PRIMARY KEY (company_id, node_id))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS idea_contact_node_scores ("
        "idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE, "
        "contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE, "
        "node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE, "
        "score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100), "
        "rationale TEXT, scored_at TEXT, "
        "PRIMARY KEY (idea_id, contact_id, node_id))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS briefings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE, "
        "idea_id INTEGER REFERENCES ideas(id) ON DELETE SET NULL, "
        "purpose TEXT, format TEXT, scheduled_at TEXT, context_notes TEXT, "
        "summary TEXT, contact_highlights TEXT, company_highlights TEXT, "
        "talking_points TEXT, open_questions TEXT, sources TEXT, "
        "status TEXT NOT NULL DEFAULT 'planned', "
        "outcome_notes TEXT, outcome_summary TEXT, "
        "interaction_id INTEGER REFERENCES interactions(id) ON DELETE SET NULL, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )

    contact_cols = {r[1] for r in db.execute("PRAGMA table_info(contacts)").fetchall()}
    contact_migrations = {
        "linkedin_raw_text": "ALTER TABLE contacts ADD COLUMN linkedin_raw_text TEXT",
        "profile_data": "ALTER TABLE contacts ADD COLUMN profile_data TEXT",
        "profile_parsed_at": "ALTER TABLE contacts ADD COLUMN profile_parsed_at TEXT",
        "company_id": "ALTER TABLE contacts ADD COLUMN company_id INTEGER",
    }
    for col, stmt in contact_migrations.items():
        if col not in contact_cols:
            db.execute(stmt)

    company_cols = {r[1] for r in db.execute("PRAGMA table_info(companies)").fetchall()}
    if "industry" not in company_cols:
        db.execute("ALTER TABLE companies ADD COLUMN industry TEXT")

    interaction_cols = {
        r[1] for r in db.execute("PRAGMA table_info(interactions)").fetchall()
    }
    interaction_migrations = {
        "source_type": (
            "ALTER TABLE interactions ADD COLUMN source_type TEXT "
            "NOT NULL DEFAULT 'recalled'"
        ),
        "topic_tags": "ALTER TABLE interactions ADD COLUMN topic_tags TEXT",
        "tone": "ALTER TABLE interactions ADD COLUMN tone TEXT",
        "analysis_rationale": "ALTER TABLE interactions ADD COLUMN analysis_rationale TEXT",
        "analyzed_at": "ALTER TABLE interactions ADD COLUMN analyzed_at TEXT",
    }
    for col, stmt in interaction_migrations.items():
        if col not in interaction_cols:
            db.execute(stmt)

    idea_contact_cols = {
        r[1] for r in db.execute("PRAGMA table_info(idea_contacts)").fetchall()
    }
    idea_contact_migrations = {
        "fit_score": "ALTER TABLE idea_contacts ADD COLUMN fit_score INTEGER",
        "fit_rationale": "ALTER TABLE idea_contacts ADD COLUMN fit_rationale TEXT",
        "scored_at": "ALTER TABLE idea_contacts ADD COLUMN scored_at TEXT",
    }
    for col, stmt in idea_contact_migrations.items():
        if col not in idea_contact_cols:
            db.execute(stmt)
    db.commit()


def get_db():
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        has_schema = g.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'contacts'"
        ).fetchone()
        if not has_schema:
            g.db.executescript((BASE_DIR / "schema.sql").read_text())
            g.db.commit()
        else:
            ensure_schema(g.db)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript((BASE_DIR / "schema.sql").read_text())
    db.commit()


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print(f"Initialized database at {DB_PATH}")


def _graph_data(db):
    nodes = db.execute("SELECT id, name FROM nodes ORDER BY name").fetchall()
    contacts = db.execute(
        "SELECT id, name, company_id FROM contacts ORDER BY name"
    ).fetchall()
    companies = db.execute("SELECT id, name FROM companies ORDER BY name").fetchall()
    contact_scores = db.execute(
        "SELECT contact_id, node_id, score FROM contact_nodes WHERE score IS NOT NULL"
    ).fetchall()
    company_scores = db.execute(
        "SELECT company_id, node_id, score FROM company_nodes WHERE score IS NOT NULL"
    ).fetchall()

    graph_nodes = []
    for n in nodes:
        graph_nodes.append({
            "id": f"node-{n['id']}", "type": "node", "label": n["name"],
            "url": url_for("contacts_list", node_id=n["id"]),
        })
    for c in contacts:
        graph_nodes.append({
            "id": f"contact-{c['id']}", "type": "contact", "label": c["name"],
            "url": url_for("contact_detail", contact_id=c["id"]),
        })
    for co in companies:
        graph_nodes.append({
            "id": f"company-{co['id']}", "type": "company", "label": co["name"],
            "url": url_for("company_detail", company_id=co["id"]),
        })

    graph_links = []
    for r in contact_scores:
        graph_links.append({
            "source": f"contact-{r['contact_id']}", "target": f"node-{r['node_id']}",
            "kind": "score", "score": r["score"],
        })
    for r in company_scores:
        graph_links.append({
            "source": f"company-{r['company_id']}", "target": f"node-{r['node_id']}",
            "kind": "score", "score": r["score"],
        })
    for c in contacts:
        if c["company_id"] is not None:
            graph_links.append({
                "source": f"contact-{c['id']}", "target": f"company-{c['company_id']}",
                "kind": "employment", "score": None,
            })

    return {"nodes": graph_nodes, "links": graph_links}


@app.route("/")
def index():
    db = get_db()
    contacts = db.execute(
        "SELECT * FROM contacts ORDER BY updated_at DESC LIMIT 5"
    ).fetchall()
    ideas = db.execute(
        "SELECT * FROM ideas WHERE status = 'active' ORDER BY updated_at DESC LIMIT 5"
    ).fetchall()
    counts = {
        "contacts": db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
        "companies": db.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
        "ideas": db.execute("SELECT COUNT(*) FROM ideas").fetchone()[0],
        "briefings": db.execute("SELECT COUNT(*) FROM briefings").fetchone()[0],
        "interactions": db.execute("SELECT COUNT(*) FROM interactions").fetchone()[0],
    }
    graph = _graph_data(db)
    return render_template(
        "index.html", contacts=contacts, ideas=ideas, counts=counts,
        graph=graph,
    )


CONTACT_SORT_OPTIONS = {"name", "newest", "oldest"}


@app.route("/contacts")
def contacts_list():
    db = get_db()
    q = request.args.get("q", "").strip()
    node_id = request.args.get("node_id", "").strip()
    sort = request.args.get("sort", "name").strip()
    if sort not in CONTACT_SORT_OPTIONS:
        sort = "name"

    query = (
        "SELECT DISTINCT c.*, "
        "(SELECT MAX(occurred_at) FROM interactions WHERE contact_id = c.id) AS last_interaction "
        "FROM contacts c "
        "LEFT JOIN contact_nodes cn ON cn.contact_id = c.id"
    )
    conditions = []
    params = []
    if q:
        conditions.append("(c.name LIKE ? OR c.company LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if node_id:
        conditions.append("cn.node_id = ?")
        params.append(node_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY c.name"

    contacts = db.execute(query, params).fetchall()
    nodes = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
    freshness_by_contact = {
        c["id"]: _freshness(c["last_interaction"] or c["created_at"]) for c in contacts
    }

    score_rows = db.execute("SELECT contact_id, node_id, score FROM contact_nodes").fetchall()
    scores_by_contact = {}
    for r in score_rows:
        scores_by_contact.setdefault(r["contact_id"], {})[r["node_id"]] = r["score"]

    if sort == "newest":
        contacts = sorted(contacts, key=lambda c: freshness_by_contact[c["id"]]["days"])
    elif sort == "oldest":
        contacts = sorted(contacts, key=lambda c: freshness_by_contact[c["id"]]["days"], reverse=True)
    else:
        contacts = sorted(contacts, key=lambda c: (c["name"] or "").lower())

    return render_template(
        "contacts_list.html",
        contacts=contacts,
        nodes=nodes,
        q=q,
        node_id=node_id,
        sort=sort,
        freshness_by_contact=freshness_by_contact,
        scores_by_contact=scores_by_contact,
    )


@app.route("/contacts/new", methods=["GET", "POST"])
def contact_new():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action", "save")
        fields = {
            "name": request.form.get("name", "").strip(),
            "company": request.form.get("company", "").strip(),
            "title": request.form.get("title", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "linkedin_url": request.form.get("linkedin_url", "").strip(),
            "bio": request.form.get("bio", "").strip(),
        }
        linkedin_text = request.form.get("linkedin_text", "").strip()

        if action == "parse":
            if not linkedin_text:
                return render_template(
                    "contact_form.html",
                    contact=fields,
                    linkedin_text=linkedin_text,
                    error="Paste some LinkedIn profile text first.",
                )
            nodes = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
            try:
                enrichment = llm.parse_and_enrich_contact(linkedin_text, nodes)
            except Exception as exc:
                return render_template(
                    "contact_form.html",
                    contact=fields,
                    linkedin_text=linkedin_text,
                    error=f"Couldn't parse with Claude: {exc}",
                )
            profile = enrichment.profile

            node_by_name = {n["name"].lower(): n for n in nodes}
            node_suggestions = []
            for s in enrichment.node_scores:
                node = node_by_name.get(s.node_name.lower())
                if node is not None:
                    node_suggestions.append(
                        {"node_id": node["id"], "node_name": node["name"],
                         "score": s.score, "rationale": s.rationale}
                    )

            company_names = []
            seen = set()
            for job in profile.work_history:
                name = job.company.strip()
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    company_names.append(name)
            current_company = (profile.current_company or "").strip()
            current_company_match = next(
                (n for n in company_names if n.lower() == current_company.lower()),
                None,
            ) if current_company else None
            if current_company_match is None:
                for job in profile.work_history:
                    name = job.company.strip()
                    if name and not job.end:
                        current_company_match = name
                        break

            return render_template(
                "contact_review.html",
                fields=fields,
                linkedin_text=linkedin_text,
                profile=profile,
                profile_json=profile.model_dump_json(),
                node_suggestions=node_suggestions,
                company_names=company_names,
                current_company_match=current_company_match,
            )

        if not fields["name"]:
            return render_template(
                "contact_form.html",
                contact=fields,
                linkedin_text=linkedin_text,
                error="Name is required.",
            )

        db.execute(
            "INSERT INTO contacts "
            "(name, company, title, email, phone, linkedin_url, bio, linkedin_raw_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fields["name"],
                fields["company"] or None,
                fields["title"] or None,
                fields["email"] or None,
                fields["phone"] or None,
                fields["linkedin_url"] or None,
                fields["bio"] or None,
                linkedin_text or None,
            ),
        )
        db.commit()
        contact_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return redirect(url_for("contact_detail", contact_id=contact_id))
    return render_template("contact_form.html", contact=None, linkedin_text="")


@app.route("/contacts/new/confirm", methods=["POST"])
def contact_new_confirm():
    db = get_db()
    name = request.form.get("name", "").strip()
    if not name:
        return render_template(
            "contact_form.html",
            contact=request.form,
            linkedin_text=request.form.get("linkedin_text", ""),
            error="Name is required.",
        )
    db.execute(
        "INSERT INTO contacts "
        "(name, company, title, email, phone, linkedin_url, bio, "
        "linkedin_raw_text, profile_data, profile_parsed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            name,
            request.form.get("company", "").strip() or None,
            request.form.get("title", "").strip() or None,
            request.form.get("email", "").strip() or None,
            request.form.get("phone", "").strip() or None,
            request.form.get("linkedin_url", "").strip() or None,
            request.form.get("bio", "").strip() or None,
            request.form.get("linkedin_text", "").strip() or None,
            request.form.get("profile_json") or None,
        ),
    )
    contact_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    node_ids = request.form.getlist("node_id")
    scores = request.form.getlist("score")
    rationales = request.form.getlist("rationale")
    for node_id, score, rationale in zip(node_ids, scores, rationales):
        score = score.strip()
        if not score:
            continue
        db.execute(
            "INSERT INTO contact_nodes (contact_id, node_id, score, notes) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(contact_id, node_id) DO UPDATE SET score = ?, notes = ?",
            (contact_id, node_id, score, rationale.strip() or None,
             score, rationale.strip() or None),
        )

    company_add = request.form.getlist("company_add")
    current_company = request.form.get("current_company", "").strip()
    current_company_id = None
    for company_name in company_add:
        company_name = company_name.strip()
        if not company_name:
            continue
        existing = db.execute(
            "SELECT * FROM companies WHERE lower(name) = lower(?)", (company_name,)
        ).fetchone()
        if existing is not None:
            company_id = existing["id"]
        else:
            db.execute("INSERT INTO companies (name) VALUES (?)", (company_name,))
            company_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        if current_company and company_name.lower() == current_company.lower():
            current_company_id = company_id

    if current_company_id is not None:
        db.execute(
            "UPDATE contacts SET company_id = ? WHERE id = ?",
            (current_company_id, contact_id),
        )

    db.commit()
    return redirect(url_for("contact_detail", contact_id=contact_id))


def _contact_detail_context(db, contact_id):
    contact = db.execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    if contact is None:
        abort(404)
    interactions = db.execute(
        "SELECT * FROM interactions WHERE contact_id = ? ORDER BY occurred_at DESC",
        (contact_id,),
    ).fetchall()
    scores = db.execute(
        "SELECT n.id, n.name, cn.score, cn.notes FROM nodes n "
        "LEFT JOIN contact_nodes cn ON cn.node_id = n.id AND cn.contact_id = ? "
        "ORDER BY n.name",
        (contact_id,),
    ).fetchall()
    ideas = db.execute(
        "SELECT i.* FROM ideas i "
        "JOIN idea_contacts ic ON ic.idea_id = i.id "
        "WHERE ic.contact_id = ? ORDER BY i.updated_at DESC",
        (contact_id,),
    ).fetchall()
    profile = json.loads(contact["profile_data"]) if contact["profile_data"] else None
    radar_labels = [s["name"] for s in scores]
    radar_values = [s["score"] if s["score"] is not None else 0 for s in scores]
    radar_unscored = [s["name"] for s in scores if s["score"] is None]
    company = None
    if contact["company_id"] is not None:
        company = db.execute(
            "SELECT * FROM companies WHERE id = ?", (contact["company_id"],)
        ).fetchone()
    all_companies = db.execute("SELECT * FROM companies ORDER BY name").fetchall()
    briefings = db.execute(
        "SELECT * FROM briefings WHERE contact_id = ? "
        "ORDER BY COALESCE(scheduled_at, created_at) DESC",
        (contact_id,),
    ).fetchall()
    last_contact_date = interactions[0]["occurred_at"] if interactions else contact["created_at"]
    return {
        "contact": contact,
        "interactions": interactions,
        "scores": scores,
        "ideas": ideas,
        "profile": profile,
        "company": company,
        "all_companies": all_companies,
        "briefings": briefings,
        "radar_labels": radar_labels,
        "radar_values": radar_values,
        "radar_unscored": radar_unscored,
        "freshness": _freshness(last_contact_date),
        "today": date.today().isoformat(),
    }


@app.route("/contacts/<int:contact_id>")
def contact_detail(contact_id):
    db = get_db()
    return render_template(
        "contact_detail.html", **_contact_detail_context(db, contact_id)
    )


@app.route("/contacts/<int:contact_id>/delete", methods=["GET", "POST"])
def delete_contact(contact_id):
    db = get_db()
    contact = db.execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    if contact is None:
        return redirect(url_for("contacts_list"))

    if request.method == "POST":
        db.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        db.commit()
        return redirect(url_for("contacts_list"))

    counts = {
        "interactions": db.execute(
            "SELECT COUNT(*) FROM interactions WHERE contact_id = ?", (contact_id,)
        ).fetchone()[0],
        "node_scores": db.execute(
            "SELECT COUNT(*) FROM contact_nodes WHERE contact_id = ?", (contact_id,)
        ).fetchone()[0],
        "ideas": db.execute(
            "SELECT COUNT(*) FROM idea_contacts WHERE contact_id = ?", (contact_id,)
        ).fetchone()[0],
    }
    return render_template("contact_delete_confirm.html", contact=contact, counts=counts)


@app.route("/contacts/<int:contact_id>/company", methods=["POST"])
def set_contact_company(contact_id):
    db = get_db()
    name = request.form.get("company_name", "").strip()
    if not name:
        db.execute(
            "UPDATE contacts SET company = NULL, company_id = NULL, "
            "updated_at = datetime('now') WHERE id = ?",
            (contact_id,),
        )
    else:
        existing = db.execute(
            "SELECT * FROM companies WHERE lower(name) = lower(?)", (name,)
        ).fetchone()
        if existing is not None:
            company_id, company_name = existing["id"], existing["name"]
        else:
            db.execute("INSERT INTO companies (name) VALUES (?)", (name,))
            company_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            company_name = name
        db.execute(
            "UPDATE contacts SET company = ?, company_id = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (company_name, company_id, contact_id),
        )
    db.commit()
    return redirect(url_for("contact_detail", contact_id=contact_id))


@app.route("/contacts/<int:contact_id>/interactions/review", methods=["POST"])
def review_interaction(contact_id):
    db = get_db()
    fields = {
        "occurred_at": request.form.get("occurred_at") or date.today().isoformat(),
        "summary": request.form.get("summary", "").strip(),
        "next_steps": request.form.get("next_steps", "").strip(),
        "source_type": request.form.get("source_type", "recalled"),
    }
    if not fields["summary"]:
        return redirect(url_for("contact_detail", contact_id=contact_id))
    try:
        analysis = llm.analyze_interaction(
            fields["summary"], fields["next_steps"], fields["source_type"]
        )
    except Exception as exc:
        return render_template(
            "contact_detail.html",
            **_contact_detail_context(db, contact_id),
            interaction_error=f"Couldn't analyze with Claude: {exc}",
            pending_interaction=fields,
        )
    return render_template(
        "interaction_review.html",
        contact=db.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone(),
        fields=fields,
        analysis=analysis,
        topic_tags_text=", ".join(analysis.topic_tags),
    )


@app.route("/contacts/<int:contact_id>/interactions/confirm", methods=["POST"])
def confirm_interaction(contact_id):
    db = get_db()
    topic_tags = [
        t.strip() for t in request.form.get("topic_tags", "").split(",") if t.strip()
    ]
    db.execute(
        "INSERT INTO interactions "
        "(contact_id, occurred_at, summary, next_steps, source_type, "
        "topic_tags, tone, analysis_rationale, analyzed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            contact_id,
            request.form.get("occurred_at") or date.today().isoformat(),
            request.form["summary"].strip(),
            request.form.get("next_steps", "").strip() or None,
            request.form.get("source_type", "recalled"),
            json.dumps(topic_tags) if topic_tags else None,
            request.form.get("tone", "").strip() or None,
            request.form.get("rationale", "").strip() or None,
        ),
    )
    db.execute(
        "UPDATE contacts SET updated_at = datetime('now') WHERE id = ?",
        (contact_id,),
    )
    db.commit()
    return redirect(url_for("contact_detail", contact_id=contact_id))


@app.route("/contacts/<int:contact_id>/nodes", methods=["POST"])
def set_contact_node(contact_id):
    db = get_db()
    node_id = request.form["node_id"]
    score = request.form["score"]
    notes = request.form.get("notes", "").strip() or None
    db.execute(
        "INSERT INTO contact_nodes (contact_id, node_id, score, notes) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(contact_id, node_id) DO UPDATE SET score = ?, notes = ?",
        (contact_id, node_id, score, notes, score, notes),
    )
    db.commit()
    return redirect(url_for("contact_detail", contact_id=contact_id))


@app.route("/contacts/<int:contact_id>/nodes/suggest", methods=["POST"])
def suggest_node_scores(contact_id):
    db = get_db()
    contact = db.execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    if contact is None:
        abort(404)
    interactions = db.execute(
        "SELECT * FROM interactions WHERE contact_id = ? ORDER BY occurred_at",
        (contact_id,),
    ).fetchall()
    nodes = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
    profile = json.loads(contact["profile_data"]) if contact["profile_data"] else None

    company = None
    company_node_scores = None
    if contact["company_id"] is not None:
        company = db.execute(
            "SELECT * FROM companies WHERE id = ?", (contact["company_id"],)
        ).fetchone()
        company_node_scores = db.execute(
            "SELECT n.name, cn.score FROM company_nodes cn "
            "JOIN nodes n ON n.id = cn.node_id WHERE cn.company_id = ?",
            (contact["company_id"],),
        ).fetchall()

    try:
        result = llm.score_contact_nodes(
            contact, profile, interactions, nodes, company, company_node_scores
        )
    except Exception as exc:
        return render_template(
            "contact_detail.html",
            **_contact_detail_context(db, contact_id),
            node_score_error=f"Couldn't score with Claude: {exc}",
        )

    node_by_name = {n["name"].lower(): n for n in nodes}
    suggestions = []
    for s in result.suggestions:
        node = node_by_name.get(s.node_name.lower())
        if node is not None:
            suggestions.append(
                {"node_id": node["id"], "node_name": node["name"],
                 "score": s.score, "rationale": s.rationale}
            )
    return render_template(
        "node_score_review.html",
        subject_name=contact["name"],
        basis_text="Claude's suggestions, based on the LinkedIn profile and logged interactions.",
        confirm_url=url_for("confirm_node_scores", contact_id=contact_id),
        contact_id=contact_id,
        suggestions=suggestions,
    )


@app.route("/contacts/<int:contact_id>/nodes/confirm_bulk", methods=["POST"])
def confirm_node_scores(contact_id):
    db = get_db()
    node_ids = request.form.getlist("node_id")
    scores = request.form.getlist("score")
    rationales = request.form.getlist("rationale")
    for node_id, score, rationale in zip(node_ids, scores, rationales):
        score = score.strip()
        if not score:
            continue
        rationale = rationale.strip() or None
        db.execute(
            "INSERT INTO contact_nodes (contact_id, node_id, score, notes) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(contact_id, node_id) DO UPDATE SET score = ?, notes = ?",
            (contact_id, node_id, score, rationale, score, rationale),
        )
    db.commit()
    return redirect(url_for("contact_detail", contact_id=contact_id))


def _company_detail_context(db, company_id):
    company = db.execute(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    if company is None:
        abort(404)
    contacts = db.execute(
        "SELECT * FROM contacts WHERE company_id = ? ORDER BY name", (company_id,)
    ).fetchall()
    scores = db.execute(
        "SELECT n.id, n.name, cn.score, cn.notes FROM nodes n "
        "LEFT JOIN company_nodes cn ON cn.node_id = n.id AND cn.company_id = ? "
        "ORDER BY n.name",
        (company_id,),
    ).fetchall()
    radar_labels = [s["name"] for s in scores]
    radar_values = [s["score"] if s["score"] is not None else 0 for s in scores]
    radar_unscored = [s["name"] for s in scores if s["score"] is None]
    return {
        "company": company,
        "contacts": contacts,
        "scores": scores,
        "radar_labels": radar_labels,
        "radar_values": radar_values,
        "radar_unscored": radar_unscored,
    }


COMPANY_SORT_OPTIONS = {"name", "newest", "oldest"}


@app.route("/companies")
def companies_list():
    db = get_db()
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "name").strip()
    if sort not in COMPANY_SORT_OPTIONS:
        sort = "name"

    query = "SELECT * FROM companies"
    params = []
    if q:
        query += " WHERE name LIKE ?"
        params.append(f"%{q}%")
    query += " ORDER BY name"
    companies = db.execute(query, params).fetchall()
    nodes = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()

    score_rows = db.execute("SELECT company_id, node_id, score FROM company_nodes").fetchall()
    scores_by_company = {}
    for r in score_rows:
        scores_by_company.setdefault(r["company_id"], {})[r["node_id"]] = r["score"]

    freshness_by_company = {}
    for c in companies:
        activity = db.execute(
            "SELECT MAX(COALESCE(i.occurred_at, ct.created_at)) AS activity_at "
            "FROM contacts ct LEFT JOIN interactions i ON i.contact_id = ct.id "
            "WHERE ct.company_id = ?",
            (c["id"],),
        ).fetchone()["activity_at"]
        freshness_by_company[c["id"]] = _freshness(activity or c["created_at"])

    if sort == "newest":
        companies = sorted(companies, key=lambda c: freshness_by_company[c["id"]]["days"])
    elif sort == "oldest":
        companies = sorted(companies, key=lambda c: freshness_by_company[c["id"]]["days"], reverse=True)
    else:
        companies = sorted(companies, key=lambda c: (c["name"] or "").lower())

    return render_template(
        "companies_list.html",
        companies=companies,
        q=q,
        sort=sort,
        nodes=nodes,
        scores_by_company=scores_by_company,
        freshness_by_company=freshness_by_company,
    )


@app.route("/companies/new", methods=["GET", "POST"])
def company_new():
    if request.method == "POST":
        db = get_db()
        name = request.form.get("name", "").strip()
        if not name:
            return render_template(
                "company_form.html", company=request.form, error="Name is required.",
                industry_options=llm.INDUSTRY_OPTIONS,
            )
        db.execute(
            "INSERT INTO companies (name, description, website, industry) "
            "VALUES (?, ?, ?, ?)",
            (
                name,
                request.form.get("description", "").strip() or None,
                request.form.get("website", "").strip() or None,
                request.form.get("industry", "").strip() or None,
            ),
        )
        db.commit()
        company_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return redirect(url_for("company_detail", company_id=company_id))
    return render_template(
        "company_form.html", company=None, industry_options=llm.INDUSTRY_OPTIONS
    )


@app.route("/companies/<int:company_id>")
def company_detail(company_id):
    db = get_db()
    return render_template(
        "company_detail.html", **_company_detail_context(db, company_id)
    )


@app.route("/companies/<int:company_id>/analyze", methods=["POST"])
def analyze_company(company_id):
    db = get_db()
    company = db.execute(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    if company is None:
        abort(404)

    # Claude never guesses which same-named company this is from the name
    # alone - without a website to anchor the search, research comes back
    # thin and scoring off that thin picture is little better than random.
    # So nothing calls Claude until a website is known.
    if not company["website"]:
        return render_template("company_request_website.html", company=company)

    return _run_company_analysis(db, company, company["website"])


@app.route("/companies/<int:company_id>/analyze/with_website", methods=["POST"])
def analyze_company_with_website(company_id):
    db = get_db()
    company = db.execute(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    if company is None:
        abort(404)
    website = request.form.get("website", "").strip()
    if not website:
        return render_template(
            "company_request_website.html",
            company=company,
            error="Enter a website to continue.",
        )
    return _run_company_analysis(db, company, website)


def _run_company_analysis(db, company, website):
    company_id = company["id"]
    contacts = db.execute(
        "SELECT * FROM contacts WHERE company_id = ? ORDER BY name", (company_id,)
    ).fetchall()
    nodes = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()

    try:
        research_result = llm.research_company(company["name"], website)
    except Exception as exc:
        return render_template(
            "company_detail.html",
            **_company_detail_context(db, company_id),
            research_error=f"Couldn't research with Claude: {exc}",
        )

    # Score against the freshly researched picture, not the stale/empty
    # description still sitting in the DB - that's what was producing
    # thin, near-random-looking grades before a website was required.
    enriched_company = dict(company)
    enriched_company["description"] = research_result.description
    enriched_company["website"] = research_result.website or website
    enriched_company["industry"] = research_result.industry or company["industry"]

    try:
        score_result = llm.score_company_nodes(enriched_company, contacts, nodes)
    except Exception as exc:
        return render_template(
            "company_detail.html",
            **_company_detail_context(db, company_id),
            node_score_error=f"Couldn't score with Claude: {exc}",
        )

    node_by_name = {n["name"].lower(): n for n in nodes}
    suggestions = []
    for s in score_result.suggestions:
        node = node_by_name.get(s.node_name.lower())
        if node is not None:
            suggestions.append(
                {"node_id": node["id"], "node_name": node["name"],
                 "score": s.score, "rationale": s.rationale}
            )

    return render_template(
        "company_analysis_review.html",
        company=company,
        description=enriched_company["description"],
        website=enriched_company["website"],
        industry=enriched_company["industry"],
        industry_options=llm.INDUSTRY_OPTIONS,
        suggestions=suggestions,
    )


@app.route("/companies/<int:company_id>/analyze/confirm", methods=["POST"])
def confirm_company_analysis(company_id):
    db = get_db()
    db.execute(
        "UPDATE companies SET description = ?, website = ?, industry = ?, "
        "updated_at = datetime('now') WHERE id = ?",
        (
            request.form.get("description", "").strip() or None,
            request.form.get("website", "").strip() or None,
            request.form.get("industry", "").strip() or None,
            company_id,
        ),
    )
    node_ids = request.form.getlist("node_id")
    scores = request.form.getlist("score")
    rationales = request.form.getlist("rationale")
    for node_id, score, rationale in zip(node_ids, scores, rationales):
        score = score.strip()
        if not score:
            continue
        rationale = rationale.strip() or None
        db.execute(
            "INSERT INTO company_nodes (company_id, node_id, score, notes) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(company_id, node_id) DO UPDATE SET score = ?, notes = ?",
            (company_id, node_id, score, rationale, score, rationale),
        )
    db.commit()
    return redirect(url_for("company_detail", company_id=company_id))


@app.route("/companies/<int:company_id>/delete", methods=["GET", "POST"])
def delete_company(company_id):
    db = get_db()
    company = db.execute(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    if company is None:
        return redirect(url_for("companies_list"))

    if request.method == "POST":
        db.execute(
            "UPDATE contacts SET company_id = NULL, company = NULL "
            "WHERE company_id = ?",
            (company_id,),
        )
        db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        db.commit()
        return redirect(url_for("companies_list"))

    counts = {
        "contacts": db.execute(
            "SELECT COUNT(*) FROM contacts WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
        "node_scores": db.execute(
            "SELECT COUNT(*) FROM company_nodes WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
    }
    return render_template(
        "company_delete_confirm.html", company=company, counts=counts
    )


@app.route("/companies/<int:company_id>/nodes", methods=["POST"])
def set_company_node(company_id):
    db = get_db()
    node_id = request.form["node_id"]
    score = request.form["score"]
    notes = request.form.get("notes", "").strip() or None
    db.execute(
        "INSERT INTO company_nodes (company_id, node_id, score, notes) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(company_id, node_id) DO UPDATE SET score = ?, notes = ?",
        (company_id, node_id, score, notes, score, notes),
    )
    db.commit()
    return redirect(url_for("company_detail", company_id=company_id))


@app.route("/nodes")
def nodes_list():
    db = get_db()
    nodes = db.execute(
        "SELECT n.*, COUNT(cn.contact_id) AS contact_count "
        "FROM nodes n LEFT JOIN contact_nodes cn ON cn.node_id = n.id "
        "GROUP BY n.id ORDER BY n.name"
    ).fetchall()
    return render_template("nodes_list.html", nodes=nodes)


@app.route("/nodes/new", methods=["POST"])
def node_new():
    db = get_db()
    db.execute(
        "INSERT INTO nodes (name, description) VALUES (?, ?)",
        (
            request.form["name"].strip(),
            request.form.get("description", "").strip() or None,
        ),
    )
    db.commit()
    return redirect(url_for("nodes_list"))


@app.route("/ideas")
def ideas_list():
    db = get_db()
    ideas = db.execute("SELECT * FROM ideas ORDER BY updated_at DESC").fetchall()
    return render_template("ideas_list.html", ideas=ideas)


@app.route("/ideas/new", methods=["GET", "POST"])
def idea_new():
    if request.method == "POST":
        db = get_db()
        db.execute(
            "INSERT INTO ideas (title, description, status) VALUES (?, ?, ?)",
            (
                request.form["title"].strip(),
                request.form.get("description", "").strip() or None,
                request.form.get("status", "active"),
            ),
        )
        db.commit()
        idea_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return redirect(url_for("idea_detail", idea_id=idea_id))
    return render_template("idea_form.html")


def _idea_detail_context(db, idea_id):
    idea = db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    if idea is None:
        abort(404)
    linked_contacts = db.execute(
        "SELECT c.*, ic.role_note, ic.fit_score, ic.fit_rationale FROM contacts c "
        "JOIN idea_contacts ic ON ic.contact_id = c.id "
        "WHERE ic.idea_id = ? ORDER BY ic.fit_score DESC, c.name",
        (idea_id,),
    ).fetchall()
    all_contacts = db.execute("SELECT * FROM contacts ORDER BY name").fetchall()
    node_score_rows = db.execute(
        "SELECT icns.contact_id, n.name AS node_name, icns.score, icns.rationale "
        "FROM idea_contact_node_scores icns "
        "JOIN nodes n ON n.id = icns.node_id "
        "WHERE icns.idea_id = ? ORDER BY icns.score DESC",
        (idea_id,),
    ).fetchall()
    node_scores_by_contact = {}
    for row in node_score_rows:
        node_scores_by_contact.setdefault(row["contact_id"], []).append(row)
    return {
        "idea": idea,
        "linked_contacts": linked_contacts,
        "all_contacts": all_contacts,
        "node_scores_by_contact": node_scores_by_contact,
    }


@app.route("/ideas/<int:idea_id>")
def idea_detail(idea_id):
    db = get_db()
    return render_template("idea_detail.html", **_idea_detail_context(db, idea_id))


@app.route("/ideas/<int:idea_id>/contacts", methods=["POST"])
def link_idea_contact(idea_id):
    db = get_db()
    contact_id = request.form["contact_id"]
    role_note = request.form.get("role_note", "").strip() or None
    db.execute(
        "INSERT INTO idea_contacts (idea_id, contact_id, role_note) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(idea_id, contact_id) DO UPDATE SET role_note = ?",
        (idea_id, contact_id, role_note, role_note),
    )
    db.execute(
        "UPDATE ideas SET updated_at = datetime('now') WHERE id = ?", (idea_id,)
    )
    db.commit()
    return redirect(url_for("idea_detail", idea_id=idea_id))


@app.route("/ideas/<int:idea_id>/contacts/suggest", methods=["POST"])
def suggest_idea_fit(idea_id):
    db = get_db()
    idea = db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    if idea is None:
        abort(404)
    contacts = db.execute("SELECT * FROM contacts ORDER BY name").fetchall()
    if not contacts:
        return redirect(url_for("idea_detail", idea_id=idea_id))

    nodes = db.execute("SELECT * FROM nodes ORDER BY name").fetchall()
    node_by_name = {n["name"].lower(): n for n in nodes}

    contacts_data = []
    for c in contacts:
        profile = json.loads(c["profile_data"]) if c["profile_data"] else None
        node_scores = db.execute(
            "SELECT n.name, cn.score FROM contact_nodes cn "
            "JOIN nodes n ON n.id = cn.node_id WHERE cn.contact_id = ?",
            (c["id"],),
        ).fetchall()
        interactions = db.execute(
            "SELECT * FROM interactions WHERE contact_id = ? "
            "ORDER BY occurred_at DESC LIMIT 5",
            (c["id"],),
        ).fetchall()
        contacts_data.append(
            {"contact": c, "profile": profile, "node_scores": node_scores,
             "interactions": interactions}
        )

    try:
        result = llm.score_idea_fit(idea, contacts_data, nodes)
    except Exception as exc:
        return render_template(
            "idea_detail.html",
            **_idea_detail_context(db, idea_id),
            fit_error=f"Couldn't score fit with Claude: {exc}",
        )

    contacts_by_id = {c["id"]: c for c in contacts}
    suggestions = []
    for s in result.suggestions:
        contact = contacts_by_id.get(s.contact_id)
        if contact is None:
            continue
        node_scores = []
        for ns in s.node_scores:
            node = node_by_name.get(ns.node_name.lower())
            if node is not None:
                node_scores.append(
                    {"node_id": node["id"], "node_name": node["name"],
                     "score": ns.score, "rationale": ns.rationale}
                )
        suggestions.append(
            {"contact_id": contact["id"], "contact_name": contact["name"],
             "score": s.overall_score, "rationale": s.overall_rationale,
             "node_scores": node_scores}
        )
    suggestions.sort(key=lambda s: -s["score"])
    return render_template("idea_fit_review.html", idea=idea, suggestions=suggestions)


@app.route("/ideas/<int:idea_id>/contacts/confirm_bulk", methods=["POST"])
def confirm_idea_fit(idea_id):
    db = get_db()
    contact_ids = request.form.getlist("contact_id")
    scores = request.form.getlist("score")
    rationales = request.form.getlist("rationale")
    for contact_id, score, rationale in zip(contact_ids, scores, rationales):
        score = score.strip()
        if not score:
            continue
        rationale = rationale.strip() or None
        db.execute(
            "INSERT INTO idea_contacts (idea_id, contact_id, fit_score, fit_rationale, scored_at) "
            "VALUES (?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(idea_id, contact_id) DO UPDATE SET "
            "fit_score = ?, fit_rationale = ?, scored_at = datetime('now')",
            (idea_id, contact_id, score, rationale, score, rationale),
        )

    node_contact_ids = request.form.getlist("node_contact_id")
    node_ids = request.form.getlist("node_node_id")
    node_scores = request.form.getlist("node_score")
    node_rationales = request.form.getlist("node_rationale")
    for contact_id, node_id, score, rationale in zip(
        node_contact_ids, node_ids, node_scores, node_rationales
    ):
        score = score.strip()
        if not score:
            continue
        rationale = rationale.strip() or None
        db.execute(
            "INSERT INTO idea_contact_node_scores "
            "(idea_id, contact_id, node_id, score, rationale, scored_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(idea_id, contact_id, node_id) DO UPDATE SET "
            "score = ?, rationale = ?, scored_at = datetime('now')",
            (idea_id, contact_id, node_id, score, rationale, score, rationale),
        )

    db.execute(
        "UPDATE ideas SET updated_at = datetime('now') WHERE id = ?", (idea_id,)
    )
    db.commit()
    return redirect(url_for("idea_detail", idea_id=idea_id))


BRIEFING_STATUS_OPTIONS = {"planned", "completed"}


@app.route("/briefings")
def briefings_list():
    db = get_db()
    status = request.args.get("status", "").strip()
    query = (
        "SELECT b.*, c.name AS contact_name FROM briefings b "
        "JOIN contacts c ON c.id = b.contact_id"
    )
    params = []
    if status in BRIEFING_STATUS_OPTIONS:
        query += " WHERE b.status = ?"
        params.append(status)
    query += " ORDER BY COALESCE(b.scheduled_at, b.created_at) DESC"
    briefings = db.execute(query, params).fetchall()
    return render_template("briefings_list.html", briefings=briefings, status=status)


@app.route("/briefings/new", methods=["GET", "POST"])
def briefing_new():
    db = get_db()
    contacts = db.execute("SELECT * FROM contacts ORDER BY name").fetchall()
    ideas = db.execute("SELECT * FROM ideas ORDER BY title").fetchall()

    if request.method == "GET":
        return render_template(
            "briefing_form.html", contacts=contacts, ideas=ideas, fields=None
        )

    fields = {
        "contact_id": request.form.get("contact_id", "").strip(),
        "idea_id": request.form.get("idea_id", "").strip(),
        "purpose": request.form.get("purpose", "").strip(),
        "format": request.form.get("format", "").strip(),
        "scheduled_at": request.form.get("scheduled_at", "").strip(),
        "context_notes": request.form.get("context_notes", "").strip(),
    }
    if not fields["contact_id"] or not fields["purpose"]:
        return render_template(
            "briefing_form.html",
            contacts=contacts,
            ideas=ideas,
            fields=fields,
            error="Pick a contact and describe the purpose first.",
        )

    contact = db.execute(
        "SELECT * FROM contacts WHERE id = ?", (fields["contact_id"],)
    ).fetchone()
    if contact is None:
        abort(404)
    profile = json.loads(contact["profile_data"]) if contact["profile_data"] else None

    company = None
    company_node_scores = None
    if contact["company_id"] is not None:
        company = db.execute(
            "SELECT * FROM companies WHERE id = ?", (contact["company_id"],)
        ).fetchone()
        company_node_scores = db.execute(
            "SELECT n.name, cn.score FROM company_nodes cn "
            "JOIN nodes n ON n.id = cn.node_id WHERE cn.company_id = ?",
            (contact["company_id"],),
        ).fetchall()

    idea = None
    idea_fit = None
    if fields["idea_id"]:
        idea = db.execute(
            "SELECT * FROM ideas WHERE id = ?", (fields["idea_id"],)
        ).fetchone()
        if idea is not None:
            idea_fit = db.execute(
                "SELECT fit_score, fit_rationale FROM idea_contacts "
                "WHERE idea_id = ? AND contact_id = ?",
                (fields["idea_id"], fields["contact_id"]),
            ).fetchone()

    interactions = db.execute(
        "SELECT * FROM interactions WHERE contact_id = ? ORDER BY occurred_at DESC",
        (fields["contact_id"],),
    ).fetchall()

    try:
        result = llm.generate_briefing(
            contact,
            profile,
            company,
            company_node_scores,
            idea,
            idea_fit,
            interactions,
            fields["purpose"],
            fields["format"],
            fields["scheduled_at"],
            fields["context_notes"],
        )
    except Exception as exc:
        return render_template(
            "briefing_form.html",
            contacts=contacts,
            ideas=ideas,
            fields=fields,
            error=f"Couldn't generate a briefing with Claude: {exc}",
        )

    return render_template(
        "briefing_review.html",
        contact=contact,
        idea=idea,
        fields=fields,
        result=result,
    )


@app.route("/briefings/confirm", methods=["POST"])
def briefing_confirm():
    db = get_db()

    def lines(name):
        return [l.strip() for l in request.form.get(name, "").splitlines() if l.strip()]

    db.execute(
        "INSERT INTO briefings "
        "(contact_id, idea_id, purpose, format, scheduled_at, context_notes, "
        "summary, contact_highlights, company_highlights, talking_points, "
        "open_questions, sources) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            request.form["contact_id"],
            request.form.get("idea_id") or None,
            request.form.get("purpose", "").strip() or None,
            request.form.get("format", "").strip() or None,
            request.form.get("scheduled_at", "").strip() or None,
            request.form.get("context_notes", "").strip() or None,
            request.form.get("summary", "").strip(),
            json.dumps(lines("contact_highlights")),
            json.dumps(lines("company_highlights")),
            json.dumps(lines("talking_points")),
            json.dumps(lines("open_questions")),
            json.dumps(lines("sources")),
        ),
    )
    db.commit()
    briefing_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return redirect(url_for("briefing_detail", briefing_id=briefing_id))


def _briefing_detail_context(db, briefing_id):
    briefing = db.execute(
        "SELECT * FROM briefings WHERE id = ?", (briefing_id,)
    ).fetchone()
    if briefing is None:
        abort(404)
    contact = db.execute(
        "SELECT * FROM contacts WHERE id = ?", (briefing["contact_id"],)
    ).fetchone()
    idea = None
    if briefing["idea_id"] is not None:
        idea = db.execute(
            "SELECT * FROM ideas WHERE id = ?", (briefing["idea_id"],)
        ).fetchone()
    return {
        "briefing": briefing,
        "contact": contact,
        "idea": idea,
        "contact_highlights": json.loads(briefing["contact_highlights"] or "[]"),
        "company_highlights": json.loads(briefing["company_highlights"] or "[]"),
        "talking_points": json.loads(briefing["talking_points"] or "[]"),
        "open_questions": json.loads(briefing["open_questions"] or "[]"),
        "sources": json.loads(briefing["sources"] or "[]"),
        "today": date.today().isoformat(),
    }


@app.route("/briefings/<int:briefing_id>")
def briefing_detail(briefing_id):
    db = get_db()
    return render_template(
        "briefing_detail.html", **_briefing_detail_context(db, briefing_id)
    )


@app.route("/briefings/<int:briefing_id>/delete", methods=["GET", "POST"])
def delete_briefing(briefing_id):
    db = get_db()
    briefing = db.execute(
        "SELECT * FROM briefings WHERE id = ?", (briefing_id,)
    ).fetchone()
    if briefing is None:
        return redirect(url_for("briefings_list"))

    if request.method == "POST":
        db.execute("DELETE FROM briefings WHERE id = ?", (briefing_id,))
        db.commit()
        return redirect(url_for("briefings_list"))

    contact = db.execute(
        "SELECT * FROM contacts WHERE id = ?", (briefing["contact_id"],)
    ).fetchone()
    return render_template(
        "briefing_delete_confirm.html", briefing=briefing, contact=contact
    )


@app.route("/briefings/<int:briefing_id>/outcome", methods=["POST"])
def review_briefing_outcome(briefing_id):
    db = get_db()
    raw_notes = request.form.get("raw_notes", "").strip()
    context = _briefing_detail_context(db, briefing_id)
    if not raw_notes:
        return render_template(
            "briefing_detail.html",
            **context,
            outcome_error="Describe what happened first.",
        )

    briefing = context["briefing"]
    contact = context["contact"]
    company = None
    if contact["company_id"] is not None:
        company = db.execute(
            "SELECT * FROM companies WHERE id = ?", (contact["company_id"],)
        ).fetchone()

    try:
        result = llm.analyze_briefing_outcome(contact, company, briefing, raw_notes)
    except Exception as exc:
        return render_template(
            "briefing_detail.html",
            **context,
            outcome_error=f"Couldn't analyze with Claude: {exc}",
            raw_notes=raw_notes,
        )

    return render_template(
        "briefing_outcome_review.html",
        briefing=briefing,
        contact=contact,
        company=company,
        result=result,
        raw_notes=raw_notes,
        today=date.today().isoformat(),
        tags_text=", ".join(result.interaction_tags),
    )


@app.route("/briefings/<int:briefing_id>/outcome/confirm", methods=["POST"])
def confirm_briefing_outcome(briefing_id):
    db = get_db()
    briefing = db.execute(
        "SELECT * FROM briefings WHERE id = ?", (briefing_id,)
    ).fetchone()
    if briefing is None:
        abort(404)
    contact_id = briefing["contact_id"]

    tags = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]
    db.execute(
        "INSERT INTO interactions "
        "(contact_id, occurred_at, summary, next_steps, source_type, "
        "topic_tags, tone, analysis_rationale, analyzed_at) "
        "VALUES (?, ?, ?, ?, 'recalled', ?, ?, ?, datetime('now'))",
        (
            contact_id,
            request.form.get("occurred_at") or date.today().isoformat(),
            request.form["summary"].strip(),
            request.form.get("next_steps", "").strip() or None,
            json.dumps(tags) if tags else None,
            request.form.get("tone", "").strip() or None,
            "Logged from meeting briefing outcome.",
        ),
    )
    interaction_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "UPDATE contacts SET updated_at = datetime('now') WHERE id = ?",
        (contact_id,),
    )

    company_update = request.form.get("company_update", "").strip()
    if company_update:
        contact = db.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        if contact["company_id"] is not None:
            db.execute(
                "UPDATE companies SET description = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (company_update, contact["company_id"]),
            )

    db.execute(
        "UPDATE briefings SET status = 'completed', outcome_notes = ?, "
        "outcome_summary = ?, interaction_id = ?, updated_at = datetime('now') "
        "WHERE id = ?",
        (
            request.form.get("raw_notes", "").strip() or None,
            request.form.get("outcome_summary", "").strip() or None,
            interaction_id,
            briefing_id,
        ),
    )
    db.commit()
    return redirect(url_for("briefing_detail", briefing_id=briefing_id))


if __name__ == "__main__":
    app.run(debug=True)
