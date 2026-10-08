-- ConTexts database schema

-- Organizations, classified against the same nodes as contacts (e.g. a
-- company can itself be an "Investor" or "Supplier")
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    website TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS company_nodes (
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    notes TEXT,
    PRIMARY KEY (company_id, node_id)
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company TEXT,
    company_id INTEGER REFERENCES companies(id),
    title TEXT,
    email TEXT,
    phone TEXT,
    linkedin_url TEXT,
    bio TEXT,
    linkedin_raw_text TEXT,
    profile_data TEXT,
    profile_parsed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Role classifications a contact can qualify for (Investor, Supplier, Cofounder, ...)
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

-- A contact's compatibility score (0-100) against a given node/classification
CREATE TABLE IF NOT EXISTS contact_nodes (
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    notes TEXT,
    PRIMARY KEY (contact_id, node_id)
);

-- Timestamped notes/logs captured after a call or meeting
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    occurred_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    next_steps TEXT,
    source_type TEXT NOT NULL DEFAULT 'recalled',
    topic_tags TEXT,
    tone TEXT,
    analysis_rationale TEXT,
    analyzed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Business/project ideas, linked to the contacts relevant to pursuing them
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Links a contact to an idea, with both a manual note and a Claude-suggested
-- values/domain fit score (separate from the contact's general node scores)
CREATE TABLE IF NOT EXISTS idea_contacts (
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    role_note TEXT,
    fit_score INTEGER,
    fit_rationale TEXT,
    scored_at TEXT,
    PRIMARY KEY (idea_id, contact_id)
);

-- Per-node breakdown of a contact's fit for a specific idea (distinct from
-- the contact's general contact_nodes score - "good Investor fit in general"
-- vs "good Investor fit for THIS idea specifically")
CREATE TABLE IF NOT EXISTS idea_contact_node_scores (
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    rationale TEXT,
    scored_at TEXT,
    PRIMARY KEY (idea_id, contact_id, node_id)
);

INSERT OR IGNORE INTO nodes (name, description) VALUES
    ('Investor', 'Provides or facilitates funding'),
    ('Supplier', 'Provides goods or services the business depends on'),
    ('Cofounder', 'Potential or actual co-founder'),
    ('Consultant', 'Provides expert advice'),
    ('Contributor/Contractor', 'Executes defined work on a contract basis');
