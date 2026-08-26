from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import json
import re
import logging
import language_tool_python
from anthropic import Anthropic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("polywrite")

app = FastAPI(title="PolyWrite API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TextRequest(BaseModel):
    text: str

# -----------------------------------------------------------------------------
# AI grammar engine
# -----------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
LLM_MODEL = os.environ.get("POLYWRITE_LLM_MODEL", "claude-sonnet-4-6")
_client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

LLM_SYSTEM_PROMPT = """
You are PolyWrite, a professional English writing assistant.
Analyze the user's English as a whole, using sentence context rather than isolated
word substitutions. Find genuine problems in grammar, spelling, punctuation,
word choice, sentence structure, and clarity. Do not invent errors.

Important:
- Preserve names, places, colleges, companies, technical terms, and other proper
  nouns exactly unless the user clearly misspells them.
- Examples of proper nouns that may appear: Sourish, Kamal, Vellore, Tamil Nadu,
  India, VIT, Java, Python.
- Correct capitalization of names and the pronoun I when appropriate.
- Understand learner English such as "I Kamal from Vellore" and infer the intended
  sentence "I am Kamal from Vellore".
- Prefer natural, minimal corrections. Do not rewrite a sentence just for style
  when it is already grammatically acceptable.
- Return ONLY valid JSON. No markdown fences and no extra text.

JSON format:
{
  "corrected_text": "fully corrected version",
  "issues": [
    {
      "type": "grammar|spelling|clarity",
      "original": "exact problematic text",
      "suggestion": "replacement",
      "explanation": "short learner-friendly explanation",
      "rule": "short rule name"
    }
  ]
}
"""


def call_llm_grammar_check(text: str):
    """Return (issues, corrected_text), or None when AI analysis is unavailable."""
    if _client is None:
        return None

    try:
        response = _client.messages.create(
            model=LLM_MODEL,
            max_tokens=2500,
            temperature=0,
            system=LLM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        raw = "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()

        # Be tolerant if a model ever surrounds JSON with whitespace/fences.
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        corrected = data.get("corrected_text", text)
        issues = data.get("issues", [])
        if not isinstance(corrected, str) or not isinstance(issues, list):
            raise ValueError("Invalid PolyWrite LLM response shape")

        cleaned = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            issue_type = issue.get("type", "grammar")
            if issue_type not in {"grammar", "spelling", "clarity"}:
                issue_type = "grammar"
            original = str(issue.get("original", "")).strip()
            suggestion = str(issue.get("suggestion", "")).strip()
            explanation = str(issue.get("explanation", "")).strip()
            if not original or not suggestion or not explanation:
                continue
            cleaned.append({
                "type": issue_type,
                "original": original,
                "suggestion": suggestion,
                "explanation": explanation,
                "rule": str(issue.get("rule", "POLYWRITE_AI")),
            })

        return cleaned, corrected
    except Exception as exc:
        logger.warning("AI grammar check failed; using local fallback: %s", exc)
        return None

# -----------------------------------------------------------------------------
# Local fallback engine
# -----------------------------------------------------------------------------
tool = language_tool_python.LanguageTool("en-US")

PROPER_NOUNS = {
    "sourish": "Sourish", "vellore": "Vellore", "india": "India",
    "chennai": "Chennai", "tamil nadu": "Tamil Nadu", "vit": "VIT",
    "java": "Java", "python": "Python",
}

IRREGULAR_PLURALS = {
    "person": "people", "child": "children", "man": "men", "woman": "women",
    "mouse": "mice", "foot": "feet", "tooth": "teeth", "goose": "geese",
}


def protect_names(text):
    protected = text
    replacements = {}
    for index, (name, proper) in enumerate(sorted(PROPER_NOUNS.items(), key=lambda x: -len(x[0]))):
        token = f"POLYNAME{index}X"
        pattern = r"\b" + re.escape(name) + r"\b"
        if re.search(pattern, protected, re.IGNORECASE):
            protected = re.sub(pattern, token, protected, flags=re.IGNORECASE)
            replacements[token] = proper
    return protected, replacements


def restore_names(text, replacements):
    for token, proper in replacements.items():
        text = re.sub(r"\b" + re.escape(token) + r"\b", proper, text, flags=re.IGNORECASE)
    return text


def preserve_case(original, suggestion):
    if not suggestion:
        return suggestion
    if original.isupper():
        return suggestion.upper()
    if original[:1].isupper():
        return suggestion[:1].upper() + suggestion[1:]
    return suggestion


def analyze_english_legacy(text: str):
    issues = []
    corrected = text

    rules = [
        (r"\b(I)\s+(?:[A-Za-z]+\s+)?from\s+([A-Za-z]+)\b", lambda m: f"{m.group(1)} am {m.group(0).split()[1] if len(m.group(0).split()) > 3 else ''} from {m.group(2)}".replace("  ", " "), "Use 'am' after I when stating where you are from."),
        (r"\b(he|she|it)\s+(?:[A-Za-z]+\s+)?from\s+([A-Za-z]+)\b", lambda m: f"{m.group(1)} is {m.group(0).split()[1] if len(m.group(0).split()) > 3 else ''} from {m.group(2)}".replace("  ", " "), "Use 'is' after he/she/it when stating where someone is from."),
        (r"\bmy\s+name\s+([A-Za-z]+)\b", lambda m: f"my name is {m.group(1)}", "Use 'is' in the expression 'my name is ...'."),
        (r"\b(he|she|it)\s+dont\b", lambda m: f"{m.group(1)} doesn't", "Use 'doesn't' with he/she/it."),
        (r"\b(I|you|we|they)\s+doesnt\b", lambda m: f"{m.group(1)} don't", "Use 'don't' with I/you/we/they."),
        (r"\b(he|she|it)\s+doesnt\b", lambda m: f"{m.group(1)} doesn't", "Use the apostrophe in 'doesn't'."),
        (r"\b(he|she|it)\s+have\b", lambda m: f"{m.group(1)} has", "Use 'has' with he/she/it."),
        (r"\b(I|you|we|they)\s+has\b", lambda m: f"{m.group(1)} have", "Use 'have' with I/you/we/they."),
        (r"\b(he|she|it)\s+do\b", lambda m: f"{m.group(1)} does", "Use 'does' with he/she/it."),
        (r"\b(he|she|it)\s+go\b", lambda m: f"{m.group(1)} goes", "Use 'goes' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+like\b", lambda m: f"{m.group(1)} likes", "Use 'likes' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+play\b", lambda m: f"{m.group(1)} plays", "Use 'plays' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+work\b", lambda m: f"{m.group(1)} works", "Use 'works' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+eat\b", lambda m: f"{m.group(1)} eats", "Use 'eats' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+want\b", lambda m: f"{m.group(1)} wants", "Use 'wants' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+need\b", lambda m: f"{m.group(1)} needs", "Use 'needs' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+study\b", lambda m: f"{m.group(1)} studies", "Use 'studies' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+were\b", lambda m: f"{m.group(1)} was", "Use 'was' with he/she/it."),
        (r"\b(he|she|it)\s+don't\b", lambda m: f"{m.group(1)} doesn't", "Use 'doesn't' with he/she/it."),
        (r"\b(he|she|it)\s+doesn't\s+([A-Za-z]+)s\b", lambda m: f"{m.group(1)} doesn't {m.group(2)}", "After 'doesn't', use the base form of the verb."),
        (r"\b(I|you|we|they)\s+don't\s+([A-Za-z]+)s\b", lambda m: f"{m.group(1)} don't {m.group(2)}", "After 'don't', use the base form of the verb."),
    ]

    for pattern, make_suggestion, explanation in rules:
        match = re.search(pattern, corrected, re.IGNORECASE)
        if not match:
            continue
        original = match.group(0)
        suggestion = preserve_case(original, make_suggestion(match))
        if suggestion.lower() == original.lower():
            continue
        issues.append({
            "type": "grammar", "original": original, "suggestion": suggestion,
            "explanation": explanation, "rule": "POLYWRITE_CUSTOM_GRAMMAR",
        })
        corrected = corrected[:match.start()] + suggestion + corrected[match.end():]

    protected, replacements = protect_names(corrected)
    matches = tool.check(protected)
    corrected = language_tool_python.utils.correct(protected, matches)
    corrected = restore_names(corrected, replacements)

    for match in matches:
        original = protected[match.offset:match.offset + match.errorLength]
        replacement = match.replacements[0] if match.replacements else ""
        if not replacement or "POLYNAME" in original or "POLYNAME" in replacement:
            continue
        rule_id = getattr(match, "ruleId", "") or ""
        upper = rule_id.upper()
        issue_type = "spelling" if "SPELL" in upper or "MORFOLOGIK" in upper else "grammar"
        issues.append({
            "type": issue_type, "original": original,
            "suggestion": preserve_case(original, replacement),
            "explanation": match.message, "rule": rule_id,
        })

    corrected = re.sub(r"(^|(?<=[.!?])\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), corrected)
    corrected = re.sub(r"\bi\b", "I", corrected)
    return issues, corrected


def analyze_english(text: str):
    # AI is the primary engine. The local engine remains a safe fallback.
    result = call_llm_grammar_check(text)
    if result is not None:
        return result
    return analyze_english_legacy(text)


@app.get("/")
def root():
    return {"message": "PolyWrite API is running", "engine": "AI + LanguageTool fallback"}


@app.post("/analyze")
def analyze(request: TextRequest):
    text = request.text.strip()
    issues, corrected_text = analyze_english(text)
    grammar = [i for i in issues if i["type"] == "grammar"]
    spelling = [i for i in issues if i["type"] == "spelling"]
    clarity = [i for i in issues if i["type"] == "clarity"]
    word_count = len(re.findall(r"\b[\w']+\b", text))
    sentence_count = len([s for s in re.split(r"[.!?]+", text) if s.strip()])
    score = max(0, min(100, 100 - len(grammar) * 8 - len(spelling) * 5 - len(clarity) * 3))

    return {
        "text": text,
        "corrected_text": corrected_text,
        "issues": issues,
        "counts": {
            "grammar": len(grammar), "spelling": len(spelling),
            "clarity": len(clarity), "total": len(issues),
        },
        "stats": {"words": word_count, "characters": len(text), "sentences": sentence_count},
        "score": score,
        "message": "Analysis complete" if issues else "No issues found",
    }
