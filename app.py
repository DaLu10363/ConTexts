import json
import os
import sqlite3
from datetime import date
from pathlib import Path

from flask import Flask, g, redirect, render_template, request, url_for

import llm

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "instance" / "contexts.db"
DB_PATH = Path(os.environ.get("CONTEXTS_DB", DEFAULT_DB_PATH))

app = Flask(__name__)
app.add_template_filter(json.loads, name="from_json")


def ensure_schema(db):
    contact_cols = {r[1] for r in db.execute("PRAGMA table_info(contacts)").fetchall()}
    contact_migrations = {
        "linkedin_raw_text": "ALTER TABLE contacts ADD COLUMN linkedin_raw_text TEXT",
        "profile_data": "ALTER TABLE contacts ADD COLUMN profile_data TEXT",
        "profile_parsed_at": "ALTER TABLE contacts ADD COLUMN profile_parsed_at TEXT",
    }
    for col, stmt in contact_migrations.items():
        if col not in contact_cols:
            db.execute(stmt)

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
        "ideas": db.execute("SELECT COUNT(*) FROM ideas").fetchone()[0],
        "interactions": db.execute("SELECT COUNT(*) FROM interactions").fetchone()[0],
    }
    return render_template(
        "index.html", contacts=contacts, ideas=ideas, counts=counts
    )


@app.route("/contacts")
def contacts_list():
    db = get_db()
    q = request.args.get("q", "").strip()
    node_id = request.args.get("node_id", "").strip()

    query = (
        "SELECT DISTINCT c.* FROM contacts c "
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
    return render_template(
        "contacts_list.html", contacts=contacts, nodes=nodes, q=q, node_id=node_id
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
            try:
                profile = llm.parse_linkedin_profile(linkedin_text)
            except Exception as exc:
                return render_template(
                    "contact_form.html",
                    contact=fields,
                    linkedin_text=linkedin_text,
                    error=f"Couldn't parse with Claude: {exc}",
                )
            return render_template(
                "contact_review.html",
                fields=fields,
                linkedin_text=linkedin_text,
                profile=profile,
                profile_json=profile.model_dump_json(),
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
    db.commit()
    contact_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return redirect(url_for("contact_detail", contact_id=contact_id))


def _contact_detail_context(db, contact_id):
    contact = db.execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
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
    return {
        "contact": contact,
        "interactions": interactions,
        "scores": scores,
        "ideas": ideas,
        "profile": profile,
        "today": date.today().isoformat(),
    }


@app.route("/contacts/<int:contact_id>")
def contact_detail(contact_id):
    db = get_db()
    return render_template(
        "contact_detail.html", **_contact_detail_context(db, contact_id)
    )


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


@app.route("/ideas/<int:idea_id>")
def idea_detail(idea_id):
    db = get_db()
    idea = db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    linked_contacts = db.execute(
        "SELECT c.*, ic.role_note FROM contacts c "
        "JOIN idea_contacts ic ON ic.contact_id = c.id "
        "WHERE ic.idea_id = ? ORDER BY c.name",
        (idea_id,),
    ).fetchall()
    all_contacts = db.execute("SELECT * FROM contacts ORDER BY name").fetchall()
    return render_template(
        "idea_detail.html",
        idea=idea,
        linked_contacts=linked_contacts,
        all_contacts=all_contacts,
    )


@app.route("/ideas/<int:idea_id>/contacts", methods=["POST"])
def link_idea_contact(idea_id):
    db = get_db()
    contact_id = request.form["contact_id"]
    role_note = request.form.get("role_note", "").strip() or None
    db.execute(
        "INSERT OR REPLACE INTO idea_contacts (idea_id, contact_id, role_note) "
        "VALUES (?, ?, ?)",
        (idea_id, contact_id, role_note),
    )
    db.execute(
        "UPDATE ideas SET updated_at = datetime('now') WHERE id = ?", (idea_id,)
    )
    db.commit()
    return redirect(url_for("idea_detail", idea_id=idea_id))


if __name__ == "__main__":
    app.run(debug=True)
