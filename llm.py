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
