import json
import os
from typing import List, Optional

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5-5"

INDUSTRY_OPTIONS = [
    "Aerospace & Defense",
    "Agriculture",
    "Automotive",
    "Biotechnology & Life Sciences",
    "Construction & Real Estate",
    "Consulting & Professional Services",
    "Consumer Goods",
    "Education",
    "Energy & Utilities",
    "Entertainment & Media",
    "Financial Services",
    "Food & Beverage",
    "Government & Public Sector",
    "Healthcare",
    "Hospitality & Travel",
    "Industrial & Manufacturing",
    "Insurance",
    "Legal",
    "Logistics & Transportation",
    "Non-profit",
    "Pharmaceuticals",
    "Retail & E-commerce",
    "Security",
    "Software & Technology",
    "Telecommunications",
    "Venture Capital & Private Equity",
    "Other",
]


class WorkHistoryItem(BaseModel):
    title: str
    company: str
    start: Optional[str] = None
    end: Optional[str] = None


class EducationItem(BaseModel):
    school: str
    degree: Optional[str] = None
    field: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None


class LinkedInProfile(BaseModel):
    full_name: Optional[str] = None
    current_role: Optional[str] = None
    current_company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    summary: str
    work_history: List[WorkHistoryItem]
    education: List[EducationItem]
    skills: List[str]


class InteractionAnalysis(BaseModel):
    topic_tags: List[str]
    tone: str
    rationale: str


class NodeScoreSuggestion(BaseModel):
    node_name: str
    score: int
    rationale: str


class NodeScoringResult(BaseModel):
    suggestions: List[NodeScoreSuggestion]


class NewContactEnrichment(BaseModel):
    profile: LinkedInProfile
    node_scores: List[NodeScoreSuggestion]


class CompanyResearch(BaseModel):
    description: str
    website: Optional[str] = None
    industry: Optional[str] = None


class BriefingResult(BaseModel):
    summary: str
    contact_highlights: List[str]
    company_highlights: List[str]
    talking_points: List[str]
    open_questions: List[str]
    sources: List[str] = []


class BriefingOutcomeResult(BaseModel):
    interaction_summary: str
    interaction_next_steps: Optional[str] = None
    interaction_tone: str
    interaction_tags: List[str]
    company_update: Optional[str] = None
    outcome_summary: str


class IdeaNodeFitScore(BaseModel):
    node_name: str
    score: int
    rationale: str


class IdeaFitSuggestion(BaseModel):
    contact_id: int
    overall_score: int
    overall_rationale: str
    node_scores: List[IdeaNodeFitScore]


class IdeaFitResult(BaseModel):
    suggestions: List[IdeaFitSuggestion]


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Set it with "
            '\'setx ANTHROPIC_API_KEY "sk-ant-..."\' in a terminal, then '
            "open a new terminal and restart the app."
        )
    return anthropic.Anthropic()


def parse_and_enrich_contact(raw_text: str, nodes) -> NewContactEnrichment:
    node_defs = "\n".join(f"- {n['name']}: {n['description'] or ''}" for n in nodes)
    response = _client().messages.parse(
        model=MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are given pasted LinkedIn profile text for a new "
                    "contact. Do two things:\n\n"
                    "1. profile: extract structured profile data. Infer "
                    "full dates where only a year is given. Capture email, "
                    "phone, and the profile's own LinkedIn URL only if they "
                    "literally appear in the text. Leave a field empty if "
                    "it isn't present. Do not invent information that "
                    "isn't there.\n\n"
                    "2. node_scores: using only that profile (there are no "
                    "logged interactions yet for this new contact), give "
                    "EACH classification listed below a 0-100 compatibility "
                    "score (0 = clearly not a fit, 100 = ideal fit) and a "
                    "one-sentence rationale grounded in specific facts from "
                    "the profile. Be conservative: if there isn't enough "
                    "information to judge a classification, score it low "
                    "and say so in the rationale rather than guessing. Use "
                    "the exact classification name given, unchanged, in "
                    "node_name.\n\n"
                    f"Classifications to score:\n{node_defs}\n\n"
                    f"Pasted profile text:\n{raw_text}"
                ),
            }
        ],
        output_format=NewContactEnrichment,
    )
    return response.parsed_output


def analyze_interaction(
    summary: str, next_steps: str, source_type: str
) -> InteractionAnalysis:
    response = _client().messages.parse(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    "Analyze this logged contact interaction. The note was "
                    f"provided as: {source_type}.\n\n"
                    f"What was discussed: {summary}\n"
                    f"Next steps: {next_steps or '(none)'}\n\n"
                    "Return 1-5 short topic tags, a one-or-two-word overall "
                    "tone/style descriptor (e.g. 'formal', 'casual', "
                    "'transactional', 'warm'), and a one-sentence rationale "
                    "explaining your tagging."
                ),
            }
        ],
        output_format=InteractionAnalysis,
    )
    return response.parsed_output


def score_contact_nodes(
    contact, profile, interactions, nodes, company=None, company_node_scores=None
) -> NodeScoringResult:
    profile_text = "(no LinkedIn profile parsed yet)"
    if profile:
        work = "; ".join(
            f"{w['title']} at {w['company']} "
            f"({w.get('start') or '?'}-{w.get('end') or 'present'})"
            for w in profile.get("work_history", [])
        ) or "(none)"
        education = "; ".join(
            f"{e['school']} ({e.get('degree') or ''} {e.get('field') or ''})".strip()
            for e in profile.get("education", [])
        ) or "(none)"
        skills = ", ".join(profile.get("skills", [])) or "(none)"
        profile_text = (
            f"Current role: {profile.get('current_role') or '?'} at "
            f"{profile.get('current_company') or '?'}\n"
            f"Summary: {profile.get('summary') or ''}\n"
            f"Work history: {work}\n"
            f"Education: {education}\n"
            f"Skills: {skills}"
        )

    interaction_lines = []
    for i in interactions:
        line = f"- [{i['occurred_at']}] ({i['source_type']}) {i['summary']}"
        if i["next_steps"]:
            line += f" Next steps: {i['next_steps']}"
        if i["tone"]:
            line += f" Tone: {i['tone']}"
        interaction_lines.append(line)
    interactions_text = "\n".join(interaction_lines) or "(no interactions logged yet)"

    node_defs = "\n".join(f"- {n['name']}: {n['description'] or ''}" for n in nodes)

    company_text = "(not linked to a company record)"
    if company:
        company_scores_text = (
            ", ".join(
                f"{s['name']}={s['score']}"
                for s in (company_node_scores or [])
                if s["score"] is not None
            )
            or "(not yet scored)"
        )
        company_text = (
            f"Currently recorded as being at: {company['name']}\n"
            f"  Industry: {company['industry'] or '(unknown)'}\n"
            f"  Company description: {company['description'] or '(none)'}\n"
            f"  Company's own node scores: {company_scores_text}\n"
            "  A company's node scores are a weak prior for a contact there, "
            "not a given - weigh them only if the contact's own work history "
            "above confirms they are CURRENTLY there (not a past employer), "
            "and discount or ignore them if the employment looks ended or "
            "uncertain."
        )

    response = _client().messages.parse(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are scoring a business contact's fit against a set "
                    "of role classifications, using everything known about "
                    "them below. For EACH classification listed, give a "
                    "0-100 compatibility score (0 = clearly not a fit, "
                    "100 = ideal fit) and a one-sentence rationale grounded "
                    "in specific facts given below. Be conservative: if "
                    "there isn't enough information to judge a "
                    "classification, score it low and say so in the "
                    "rationale rather than guessing. Use the exact "
                    "classification name given, unchanged, in node_name.\n\n"
                    f"Contact: {contact['name']}\n"
                    f"Bio: {contact['bio'] or '(none)'}\n\n"
                    f"LinkedIn profile:\n{profile_text}\n\n"
                    f"Company affiliation:\n{company_text}\n\n"
                    f"Logged interactions:\n{interactions_text}\n\n"
                    f"Classifications to score:\n{node_defs}"
                ),
            }
        ],
        output_format=NodeScoringResult,
    )
    return response.parsed_output


def score_idea_fit(idea, contacts_data, nodes) -> IdeaFitResult:
    def format_profile(profile):
        if not profile:
            return "(no LinkedIn profile parsed yet)"
        work = "; ".join(
            f"{w['title']} at {w['company']}" for w in profile.get("work_history", [])
        ) or "(none)"
        skills = ", ".join(profile.get("skills", [])) or "(none)"
        return (
            f"Summary: {profile.get('summary') or ''}\n"
            f"  Work history: {work}\n"
            f"  Skills: {skills}"
        )

    def format_interactions(interactions):
        lines = []
        for i in interactions:
            line = f"  - [{i['occurred_at']}] {i['summary']}"
            if i["tone"]:
                line += f" (tone: {i['tone']})"
            lines.append(line)
        return "\n".join(lines) or "  (no interactions logged)"

    contact_blocks = []
    for c in contacts_data:
        contact = c["contact"]
        node_scores_text = ", ".join(
            f"{n['name']}={n['score']}" for n in c["node_scores"] if n["score"] is not None
        ) or "(none scored yet)"
        contact_blocks.append(
            f"id={contact['id']}: {contact['name']}\n"
            f"  Bio: {contact['bio'] or '(none)'}\n"
            f"  Node scores: {node_scores_text}\n"
            f"  {format_profile(c['profile'])}\n"
            f"  Recent interactions:\n{format_interactions(c['interactions'])}"
        )
    contacts_text = "\n\n".join(contact_blocks)
    node_defs = "\n".join(f"- {n['name']}: {n['description'] or ''}" for n in nodes)

    response = _client().messages.parse(
        model=MODEL,
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are judging how well each contact below fits a "
                    "specific business idea/project - not just their general "
                    "role (investor, cofounder, etc.), but whether the "
                    "idea's domain, values, and mission plausibly align with "
                    "what you know about them. For example, an investor "
                    "focused on social-justice causes is a poor fit for a "
                    "defense/weapons startup even if they score well "
                    "generally as an 'Investor' node, and vice versa.\n\n"
                    "For EACH contact, give:\n"
                    "1. An overall_score (0-100) and overall_rationale for "
                    "how well this contact's apparent values/domain align "
                    "with this specific idea.\n"
                    "2. node_scores: a 0-100 score and one-sentence "
                    "rationale for EACH of the classifications listed below, "
                    "but scoped specifically to this idea - e.g. a contact "
                    "might generally be a strong 'Investor' but a weak "
                    "'Investor' specifically for this idea if the domain "
                    "conflicts with their apparent values. Use the exact "
                    "classification name given, unchanged, in node_name.\n\n"
                    "Be conservative: if there isn't enough information to "
                    "judge alignment, score around 50 and say so, rather "
                    "than guessing at values you have no evidence for. Use "
                    "the exact numeric id given for each contact in your "
                    "response.\n\n"
                    f"Idea: {idea['title']}\n"
                    f"Description: {idea['description'] or '(none)'}\n\n"
                    f"Classifications to score per contact:\n{node_defs}\n\n"
                    f"Contacts:\n{contacts_text}"
                ),
            }
        ],
        output_format=IdeaFitResult,
    )
    return response.parsed_output


def score_company_nodes(company, contacts_at_company, nodes) -> NodeScoringResult:
    if contacts_at_company:
        people_lines = []
        for c in contacts_at_company:
            line = f"- {c['name']}"
            if c["title"]:
                line += f", {c['title']}"
            if c["bio"]:
                line += f": {c['bio']}"
            people_lines.append(line)
        people_text = "\n".join(people_lines)
    else:
        people_text = "(no contacts logged at this company yet)"

    node_defs = "\n".join(f"- {n['name']}: {n['description'] or ''}" for n in nodes)

    response = _client().messages.parse(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are scoring a company's fit against a set of role "
                    "classifications, the same ones used for individual "
                    "contacts (e.g. a company itself can be an 'Investor' or "
                    "a 'Supplier'). For EACH classification listed, give a "
                    "0-100 compatibility score (0 = clearly not a fit, "
                    "100 = ideal fit) and a one-sentence rationale grounded "
                    "in specific facts given below. Be conservative: if "
                    "there isn't enough information to judge a "
                    "classification, score it low and say so in the "
                    "rationale rather than guessing. Use the exact "
                    "classification name given, unchanged, in node_name.\n\n"
                    f"Company: {company['name']}\n"
                    f"Industry: {company['industry'] or '(unknown)'}\n"
                    f"Description: {company['description'] or '(none)'}\n"
                    f"Website: {company['website'] or '(none)'}\n\n"
                    f"Known contacts at this company:\n{people_text}\n\n"
                    f"Classifications to score:\n{node_defs}"
                ),
            }
        ],
        output_format=NodeScoringResult,
    )
    return response.parsed_output


def research_company(name: str, website: Optional[str] = None) -> CompanyResearch:
    context = (
        f"Their known website is {website}."
        if website
        else "No website is known yet - try to find their official site."
    )
    industry_list = "\n".join(f"- {i}" for i in INDUSTRY_OPTIONS)
    response = _client().messages.create(
        model=MODEL,
        max_tokens=2048,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
        messages=[
            {
                "role": "user",
                "content": (
                    f'Research the company "{name}" using web search. '
                    f"{context} Write a concise 2-4 sentence description "
                    "covering what they do, their industry, and any "
                    "publicly stated mission or values (useful later for "
                    "judging whether this company aligns with a potential "
                    "investor's or partner's values). Base this only on "
                    "what you actually find - do not invent details. If "
                    "you cannot find reliable information, say so briefly "
                    "in the description instead of guessing.\n\n"
                    "Also pick the single best-fitting industry/sector for "
                    f"them from exactly this list (use the label verbatim, "
                    "unchanged):\n"
                    f"{industry_list}\n\n"
                    "After searching, respond with ONLY a JSON object, no "
                    "other text, no markdown code fences, in exactly this "
                    'shape: {"description": "...", "website": "https://... '
                    'or null", "industry": "one of the exact labels above, '
                    'or null if you truly can\'t tell"}'
                ),
            }
        ],
    )
    texts = [b.text for b in response.content if b.type == "text"]
    raw = texts[-1].strip() if texts else ""
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Claude's response wasn't valid JSON: {raw[:200]!r}"
        ) from exc
    return CompanyResearch(**data)


def generate_briefing(
    contact,
    profile,
    company,
    company_node_scores,
    idea,
    idea_fit,
    interactions,
    purpose,
    format_,
    scheduled_at,
    context_notes,
) -> BriefingResult:
    profile_text = "(no LinkedIn profile parsed yet)"
    if profile:
        work = "; ".join(
            f"{w['title']} at {w['company']} "
            f"({w.get('start') or '?'}-{w.get('end') or 'present'})"
            for w in profile.get("work_history", [])
        ) or "(none)"
        profile_text = (
            f"Current role: {profile.get('current_role') or '?'} at "
            f"{profile.get('current_company') or '?'}\n"
            f"Summary: {profile.get('summary') or ''}\n"
            f"Work history: {work}\n"
            f"Skills: {', '.join(profile.get('skills', [])) or '(none)'}"
        )

    interaction_lines = []
    for i in interactions:
        line = f"- [{i['occurred_at']}] {i['summary']}"
        if i["next_steps"]:
            line += f" Next steps: {i['next_steps']}"
        interaction_lines.append(line)
    interactions_text = "\n".join(interaction_lines) or "(no interactions logged yet)"

    company_text = "(not linked to a company record)"
    if company:
        scores_text = (
            ", ".join(
                f"{s['name']}={s['score']}"
                for s in (company_node_scores or [])
                if s["score"] is not None
            )
            or "(not yet scored)"
        )
        company_text = (
            f"{company['name']}\n"
            f"  Industry: {company['industry'] or '(unknown)'}\n"
            f"  Description: {company['description'] or '(none)'}\n"
            f"  Website: {company['website'] or '(none)'}\n"
            f"  Node scores: {scores_text}"
        )

    idea_text = "(no idea linked to this briefing)"
    if idea:
        idea_text = f"{idea['title']}: {idea['description'] or '(no description)'}"
        if idea_fit and idea_fit["fit_score"] is not None:
            idea_text += (
                f"\n  This contact's fit for this idea: "
                f"{idea_fit['fit_score']}/100 - {idea_fit['fit_rationale'] or ''}"
            )

    response = _client().messages.create(
        model=MODEL,
        max_tokens=4096,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
        messages=[
            {
                "role": "user",
                "content": (
                    "You are preparing a briefing for the user ahead of an "
                    "upcoming communication with a business contact. Use "
                    "everything known below, AND use web search to find "
                    "anything current and public about this person and "
                    "their company that could be useful for this specific "
                    "purpose (e.g. recent news, funding rounds, programs, "
                    "calls for proposals, public statements). Only state "
                    "things you actually find via search or that are given "
                    "below - do not invent facts.\n\n"
                    f"Upcoming communication:\n"
                    f"  Purpose: {purpose}\n"
                    f"  Format: {format_ or '(unspecified)'}\n"
                    f"  Scheduled: {scheduled_at or '(unspecified)'}\n"
                    f"  Additional context from the user: {context_notes or '(none)'}\n\n"
                    f"Contact: {contact['name']}\n"
                    f"Bio: {contact['bio'] or '(none)'}\n"
                    f"LinkedIn profile:\n{profile_text}\n\n"
                    f"Company affiliation:\n{company_text}\n\n"
                    f"Idea this meeting may relate to:\n{idea_text}\n\n"
                    f"Past logged interactions:\n{interactions_text}\n\n"
                    "After researching, respond with ONLY a JSON object, no "
                    "other text, no markdown code fences, in exactly this "
                    'shape: {"summary": "one paragraph on why this meeting '
                    'matters and the overall approach", '
                    '"contact_highlights": ["..."], '
                    '"company_highlights": ["..."], '
                    '"talking_points": ["..."], '
                    '"open_questions": ["..."], '
                    '"sources": ["https://... (URLs actually found via web '
                    'search, empty list if none)"]}'
                ),
            }
        ],
    )
    texts = [b.text for b in response.content if b.type == "text"]
    raw = texts[-1].strip() if texts else ""
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Claude's response wasn't valid JSON: {raw[:200]!r}"
        ) from exc
    return BriefingResult(**data)


def analyze_briefing_outcome(contact, company, briefing, raw_notes) -> BriefingOutcomeResult:
    talking_points = (
        json.loads(briefing["talking_points"]) if briefing["talking_points"] else []
    )
    company_line = (
        f"{company['name']} (existing description: "
        f"{company['description'] or '(none)'})"
        if company
        else "(none linked - company_update must be null)"
    )
    response = _client().messages.parse(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": (
                    "The user just had a planned communication with a "
                    "business contact and typed raw notes about what "
                    "happened. Turn this into a structured record.\n\n"
                    "1. Produce a normal interaction log entry: "
                    "interaction_summary (what was discussed/happened), "
                    "interaction_next_steps (if any were mentioned, else "
                    "leave empty), interaction_tone (one-or-two-word style "
                    "descriptor), interaction_tags (1-5 short topic "
                    "tags).\n\n"
                    "2. Separately, decide whether any part of the notes is "
                    "really an organizational/company-level fact (e.g. a "
                    "program, deadline, call for proposals, funding focus) "
                    "rather than something personal to this contact. If so, "
                    "set company_update to a revised, concise company "
                    "description that folds the new fact(s) into the "
                    "company's existing description (keep what's still "
                    "true, add the new information, don't just append raw "
                    "notes verbatim). If nothing company-level came up, or "
                    "no company is linked, set company_update to null.\n\n"
                    "3. Give a one-to-two sentence outcome_summary of how "
                    "this communication went relative to its original "
                    "purpose and talking points.\n\n"
                    f"Contact: {contact['name']}\n"
                    f"Company: {company_line}\n\n"
                    f"Original purpose of this communication: "
                    f"{briefing['purpose'] or '(unspecified)'}\n"
                    f"Planned talking points were: "
                    f"{', '.join(talking_points) or '(none)'}\n\n"
                    f"User's raw notes on what happened:\n{raw_notes}"
                ),
            }
        ],
        output_format=BriefingOutcomeResult,
    )
    return response.parsed_output
