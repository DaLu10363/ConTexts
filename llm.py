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
