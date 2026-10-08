import os
from typing import List, Optional

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5-5"


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


def parse_linkedin_profile(raw_text: str) -> LinkedInProfile:
    response = _client().messages.parse(
        model=MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract structured profile data from this pasted "
                    "LinkedIn profile text. Infer full dates where only a "
                    "year is given. Leave a field empty if it isn't present "
                    "in the text. Do not invent information that isn't "
                    "there.\n\n" + raw_text
                ),
            }
        ],
        output_format=LinkedInProfile,
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


def score_contact_nodes(contact, profile, interactions, nodes) -> NodeScoringResult:
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
