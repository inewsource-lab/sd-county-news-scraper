"""AI helpers: summarization, urgency, relevance, group summary, suggested angle."""
import logging
from typing import List, Dict, Optional, Tuple

from . import llm

logger = logging.getLogger(__name__)


def summarize_article(title: str, excerpt: str) -> Optional[str]:
    """
    One-sentence summary of an article for journalists.
    
    Returns:
        One-sentence summary or None if API unavailable
    """
    if not llm.is_available():
        return None
    prompt = f"""Summarize this news item in one clear sentence for a journalist scanning a digest. Be factual and neutral.

Title: {title}
Summary: {excerpt[:800] if excerpt else "(none)"}

Reply with only the one-sentence summary, no preamble."""
    return llm.chat(prompt, max_tokens=150)


def classify_urgency(title: str, excerpt: str) -> str:
    """
    Classify article as breaking, developing, or routine.
    
    Returns:
        "breaking", "developing", or "routine"; "routine" on API failure
    """
    if not llm.is_available():
        return "routine"
    prompt = f"""Classify this news headline and summary as exactly one word: breaking, developing, or routine.
- breaking: just happened, urgent, breaking news
- developing: story still unfolding
- routine: standard coverage, not urgent

Title: {title}
Summary: {(excerpt or "")[:500]}

Reply with only one word: breaking, developing, or routine."""
    out = llm.chat(prompt, max_tokens=10)
    if not out:
        return "routine"
    out = out.lower().strip()
    if out in ("breaking", "developing", "routine"):
        return out
    return "routine"


def ai_relevance(title: str, excerpt: str, communities: List[str]) -> List[str]:
    """
    Which of the given communities is this story relevant to? (When place name isn't in text.)
    
    Returns:
        List of community names (0–3) that are relevant, or empty list
    """
    if not llm.is_available() or not communities:
        return []
    communities_str = ", ".join(communities)
    prompt = f"""These are San Diego County community names: {communities_str}

Task: Reply with a community from the list ONLY if the story is explicitly about something happening IN that community (e.g. event there, local government, local school, local business, local incident). Otherwise reply "none".

You MUST reply "none" for:
- Any story about a place NOT in the list (e.g. La Jolla, San Diego city, National City). That includes research or institutions in another place (e.g. Salk Institute is in La Jolla — reply "none").
- Celebrity news, obituaries, entertainment, or personality stories with no mention of a listed community or an event in one.
- Science, research, or general interest with no specific tie to one of the listed communities.
- Broad regional or "San Diego" stories with no specific community named.
- Any doubt. Default is "none"; do not guess.

Title: {title}
Summary: {(excerpt or "")[:600]}

Reply with only a comma-separated list of community names from the list above (up to 3), or the single word "none". No other text."""
    out = llm.chat(prompt, max_tokens=80)
    if not out or out.strip().lower() == "none":
        return []
    # Parse comma-separated; normalize to match config names
    found = []
    for part in out.split(","):
        name = part.strip()
        if not name:
            continue
        # Match against config (case-insensitive then use first match)
        for c in communities:
            if c.lower() == name.lower():
                found.append(c)
                break
    return found[:3]


def batch_ai_relevance(
    candidates: List[Tuple[str, str]],
    communities: List[str],
) -> List[List[str]]:
    """
    For each (title, excerpt), return list of relevant community names.
    
    Returns:
        List of list of community names, same length as candidates
    """
    if not llm.is_available() or not candidates or not communities:
        return [[] for _ in candidates]
    communities_str = ", ".join(communities)
    lines = []
    for i, (title, excerpt) in enumerate(candidates):
        excerpt_snippet = (excerpt or "")[:400]
        lines.append(f"Article {i + 1}:\nTitle: {title}\nSummary: {excerpt_snippet}")
    prompt = f"""These are San Diego County community names: {communities_str}

Task: For each article, reply with a community from the list ONLY if the story is explicitly about something happening IN that community (event there, local government, local school, local business). Otherwise reply "none".

You MUST reply "none" for: stories about a place not in the list (e.g. La Jolla, San Diego city — including Salk Institute in La Jolla); celebrity/obituary/entertainment with no listed-community tie; science/research/general interest with no specific community; broad "San Diego" stories; or any doubt. Default is "none"; do not guess.

Reply with exactly one line per article: comma-separated community names from the list above, or the word "none". Same number of lines as articles.

{chr(10).join(lines)}"""
    out = llm.chat(prompt, max_tokens=400)
    if not out:
        return [[] for _ in candidates]
    result = []
    for line in out.strip().split("\n"):
        line = line.strip()
        # Handle "Article N: ..." or "1. ..." or plain "A, B"
        if ":" in line:
            line = line.split(":", 1)[1].strip()
        if line.lower() == "none":
            result.append([])
            continue
        found = []
        for part in line.replace(",", " ").split():
            part = part.strip(".,")
            if not part:
                continue
            for c in communities:
                if c.lower() == part.lower():
                    found.append(c)
                    break
        result.append(found[:3])
    # Pad if we got fewer lines than candidates
    while len(result) < len(candidates):
        result.append([])
    return result[: len(candidates)]


def batch_verify_community_relevance(
    items: List[Tuple[str, str, str]],
) -> List[bool]:
    """
    Second-pass check: for each (title, excerpt, community), is this story
    specifically about something happening IN that community?
    Returns one bool per item. On API failure or parse error, returns False for that item.
    """
    if not llm.is_available() or not items:
        return [False] * len(items)
    lines = []
    for i, (title, excerpt, community) in enumerate(items):
        excerpt_snippet = (excerpt or "")[:350]
        lines.append(f"{i + 1}. Community: {community}\nTitle: {title}\nSummary: {excerpt_snippet}")
    prompt = f"""For each item below, answer: Is this story specifically about something happening IN the given community (e.g. event there, local government, local school, local business in that city)? Not just "San Diego area" or general interest—it must be clearly about that community.

Reply with exactly one word per item: "yes" or "no". Same number of lines as items. No other text.

{chr(10).join(lines)}"""
    out = llm.chat(prompt, max_tokens=len(items) * 10 + 20)
    if not out:
        return [False] * len(items)
    result = []
    for line in out.strip().split("\n"):
        line = line.strip()
        if ":" in line:
            line = line.split(":", 1)[1].strip()
        result.append(line.lower().startswith("y"))
    while len(result) < len(items):
        result.append(False)
    return result[: len(items)]


def synthesize_group_summary(articles: List[Dict]) -> Optional[str]:
    """
    One clear 1–2 sentence summary for a group of similar articles.
    
    Returns:
        Summary string or None
    """
    if not llm.is_available() or not articles:
        return None
    parts = []
    for i, a in enumerate(articles[:5]):  # cap at 5
        title = a.get("title", "")
        excerpt = (a.get("excerpt") or "")[:300]
        parts.append(f"{i + 1}. Title: {title}\n   Summary: {excerpt}")
    prompt = f"""These headlines and excerpts are about the same story from different outlets. Write one clear 1–2 sentence summary that captures the main fact. Be neutral and factual.

{chr(10).join(parts)}

Reply with only the summary, no preamble."""
    return llm.chat(prompt, max_tokens=150)


def suggest_angle(articles: List[Dict]) -> Optional[str]:
    """
    Suggest an undercovered angle or follow-up for journalists.
    
    Returns:
        One to two sentences or None
    """
    if not llm.is_available() or not articles:
        return None
    parts = []
    for a in articles[:5]:
        parts.append(f"- {a.get('title', '')} | {(a.get('excerpt') or '')[:200]}")
    prompt = f"""These headlines/summaries cover the same story. In 1–2 sentences, what angle is undercovered or what's a natural follow-up for a journalist? Be specific and actionable.

{chr(10).join(parts)}

Reply with only the suggested angle, no preamble."""
    return llm.chat(prompt, max_tokens=150)


def group_summary_and_angle(articles: List[Dict]) -> Tuple[Optional[str], Optional[str]]:
    """
    Get both group summary and suggested angle in one call to save cost.
    
    Returns:
        (summary, angle) — either may be None
    """
    if not llm.is_available() or not articles:
        return None, None
    parts = []
    for i, a in enumerate(articles[:5]):
        title = a.get("title", "")
        excerpt = (a.get("excerpt") or "")[:250]
        parts.append(f"{i + 1}. {title}\n   {excerpt}")
    prompt = f"""These are about the same story from different outlets.

{chr(10).join(parts)}

Reply with exactly two short paragraphs:
1) SUMMARY: One clear 1–2 sentence summary of the main fact.
2) ANGLE: One to two sentences suggesting an undercovered angle or follow-up for a journalist.

Use the labels "SUMMARY:" and "ANGLE:" so they can be parsed."""
    out = llm.chat(prompt, max_tokens=300)
    if not out:
        return None, None
    summary = None
    angle = None
    if "SUMMARY:" in out:
        a = out.split("SUMMARY:", 1)[1]
        if "ANGLE:" in a:
            summary = a.split("ANGLE:")[0].strip()
            angle = a.split("ANGLE:", 1)[1].strip()
        else:
            summary = a.strip()
    if "ANGLE:" in out and angle is None:
        angle = out.split("ANGLE:", 1)[1].strip()
    return summary or None, angle or None
