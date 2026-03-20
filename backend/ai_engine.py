"""
All OpenAI API calls:
  - ATS scoring (of the tailored resume)
  - Resume tailoring
  - Cover letter generation
"""
import json
import re
import sys
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

client = OpenAI(api_key=config.OPENAI_API_KEY)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _profile_to_text(profile: dict) -> str:
    lines = ["=== SKILLS ==="]
    for cat, skills in profile.get("skills", {}).items():
        label = profile.get("skills_labels", {}).get(cat, cat)
        lines.append(f"  {label}: {', '.join(skills)}")

    lines.append("\n=== EXPERIENCE ===")
    for exp in profile.get("experience", []):
        lines.append(f"  {exp['role']} | {exp['company']} | {exp.get('period','')} | {exp.get('location','')}")
        for b in exp.get("bullets", []):
            lines.append(f"    • {b}")

    lines.append("\n=== PROJECTS ===")
    for p in profile.get("projects", []):
        lines.append(f"  {p['name']}")
        for b in p.get("bullets", []):
            lines.append(f"    • {b}")

    lines.append("\n=== EDUCATION ===")
    for e in profile.get("education", []):
        lines.append(f"  {e['degree']} – {e['institution']} ({e.get('period','')})")

    return "\n".join(lines)


def _tailored_to_text(tailored: dict, profile: dict) -> str:
    lines = []
    if tailored.get("professional_summary"):
        lines.append(f"SUMMARY:\n{tailored['professional_summary']}\n")

    lines.append("SKILLS:")
    skill_keys = tailored.get("skills_order") or list(profile["skills"].keys())
    labels = profile.get("skills_labels", {})
    for key in skill_keys:
        skills = profile["skills"].get(key, [])
        if skills:
            lines.append(f"  {labels.get(key, key)}: {', '.join(skills)}")

    lines.append("\nEXPERIENCE:")
    tailored_exp_map = {(e["role"], e["company"]): e for e in tailored.get("experience", [])}
    for orig in profile.get("experience", []):
        use = tailored_exp_map.get((orig["role"], orig["company"]), orig)
        lines.append(f"  {use['role']} at {use['company']} ({use.get('period','')})")
        for b in use.get("bullets", orig.get("bullets", [])):
            lines.append(f"    • {b}")

    lines.append("\nPROJECTS:")
    for p in tailored.get("projects", profile.get("projects", [])):
        lines.append(f"  {p['name']}")
        for b in p.get("bullets", []):
            lines.append(f"    • {b}")

    return "\n".join(lines)


def _parse_json(text: str) -> dict:
    """Extract JSON from response even if wrapped in markdown fences."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def _chat(system: str, user: str, max_tokens: int = 2000) -> str:
    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


# ── ATS Scoring ────────────────────────────────────────────────────────────────

def score_job(job_description: str, profile: dict, tailored: dict = None) -> dict:
    """
    Score the resume against the job description.
    If tailored is provided, scores the TAILORED resume.
    """
    if tailored:
        resume_text  = _tailored_to_text(tailored, profile)
        context_note = "This is an ATS-optimised tailored resume."
    else:
        resume_text  = _profile_to_text(profile)
        context_note = "This is the candidate's standard resume."

    system = "You are an expert ATS analyst. Return only valid JSON, no markdown."
    user   = f"""{context_note} Score this resume against the job description.

JOB DESCRIPTION:
{job_description}

RESUME:
{resume_text}

Return JSON exactly:
{{
  "score": <integer 0-100>,
  "matched_keywords": [<up to 12 keywords found in both>],
  "missing_keywords": [<up to 6 important keywords missing from resume>],
  "requires_pr_citizen": <true if job explicitly requires Australian citizenship or PR, else false>,
  "reason": "<2-3 sentence explanation>"
}}

Scoring: 90-100 near-perfect, 75-89 strong, 60-74 moderate, 0-59 poor."""

    return _parse_json(_chat(system, user, max_tokens=800))


# ── Resume Tailoring ───────────────────────────────────────────────────────────

def tailor_resume(job_description: str, profile: dict) -> dict:
    """
    Returns a tailored version of the profile targeted at the job.
    """
    profile_text = _profile_to_text(profile)

    system = "You are a professional resume writer specialising in ATS optimisation. Return only valid JSON, no markdown."
    user   = f"""Tailor this candidate's resume for the job below.

RULES:
1. Do NOT invent experience, skills, or achievements not in the original profile.
2. Rewrite bullet points to incorporate job-relevant keywords naturally.
3. Put the most relevant bullets first within each role.
4. Write a 3-4 sentence professional summary targeting this exact role.
5. Reorder skills categories to prioritise what the job values most.
6. Keep all original employers, dates, and locations unchanged.

JOB DESCRIPTION:
{job_description}

ORIGINAL PROFILE:
{profile_text}

Return JSON exactly:
{{
  "professional_summary": "<3-4 sentence summary>",
  "skills_order": ["programming","database","visualization","ml_analytics","business"],
  "experience": [
    {{
      "role": "<original role>",
      "company": "<original company>",
      "period": "<original period>",
      "location": "<original location>",
      "bullets": ["<tailored bullet>", ...]
    }}
  ],
  "projects": [
    {{
      "name": "<original project name>",
      "org": "<org if any>",
      "period": "<period if any>",
      "bullets": ["<tailored bullet>", ...]
    }}
  ],
  "key_changes": "<1-2 sentences on what was emphasised>"
}}"""

    return _parse_json(_chat(system, user, max_tokens=3000))


# ── Cover Letter ───────────────────────────────────────────────────────────────

def generate_cover_letter(job_description: str, profile: dict,
                           company: str, job_title: str) -> str:
    """Returns a plain-text cover letter (no markdown)."""
    profile_text = _profile_to_text(profile)
    personal     = profile.get("personal", {})

    system = "You are a professional cover letter writer. Return only the cover letter text, no markdown."
    user   = f"""Write a compelling cover letter for this application.

GUIDELINES:
- Max 350 words, 3-4 paragraphs
- Strong opening that references the role and company — not "I am writing to apply..."
- Body: connect 2 specific achievements to the key job requirements
- Show awareness of the company/industry; link to candidate's experience
- Closing: confident call to action, enthusiasm, mention availability
- Tone: professional but warm and human
- No clichés like "team player", "hard worker", "passionate about data"
- Start with: Dear Hiring Manager,

CANDIDATE: {personal.get('name', 'Antone Martin')}
JOB TITLE: {job_title}
COMPANY: {company}

JOB DESCRIPTION:
{job_description}

CANDIDATE PROFILE:
{profile_text}"""

    return _chat(system, user, max_tokens=800)
