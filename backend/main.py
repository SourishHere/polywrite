from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
import logging
import language_tool_python

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


# LanguageTool is the main local grammar engine. It covers grammar, spelling,
# punctuation, agreement, word choice, sentence structure and many other rules.
tool = language_tool_python.LanguageTool("en-US")

# Common names/places/technical terms that an English dictionary may flag.
# This is a small protection list, not the grammar engine itself.
PROPER_NOUNS = {
    "sourish": "Sourish",
    "kamal": "Kamal",
    "vellore": "Vellore",
    "chennai": "Chennai",
    "bangalore": "Bangalore",
    "bengaluru": "Bengaluru",
    "hyderabad": "Hyderabad",
    "tamil nadu": "Tamil Nadu",
    "india": "India",
    "vit": "VIT",
    "java": "Java",
    "python": "Python",
    "javascript": "JavaScript",
}


def protect_proper_nouns(text: str):
    protected = text
    replacements = {}
    for index, (name, proper) in enumerate(
        sorted(PROPER_NOUNS.items(), key=lambda item: -len(item[0]))
    ):
        token = f"POLYNAME{index}TOKEN"
        pattern = r"\b" + re.escape(name) + r"\b"
        if re.search(pattern, protected, re.IGNORECASE):
            protected = re.sub(pattern, token, protected, flags=re.IGNORECASE)
            replacements[token] = proper
    return protected, replacements


def restore_proper_nouns(text: str, replacements):
    for token, proper in replacements.items():
        text = re.sub(r"\b" + re.escape(token) + r"\b", proper, text, flags=re.IGNORECASE)
    return text


def preserve_case(original: str, suggestion: str):
    if not suggestion:
        return suggestion
    if original.isupper():
        return suggestion.upper()
    if original[:1].isupper():
        return suggestion[:1].upper() + suggestion[1:]
    return suggestion


def add_issue(issues, issue_type, original, suggestion, explanation, rule):
    if not original or not suggestion or original == suggestion:
        return
    key = (issue_type, original.lower(), suggestion.lower())
    if any((i["type"], i["original"].lower(), i["suggestion"].lower()) == key for i in issues):
        return
    issues.append({
        "type": issue_type,
        "original": original,
        "suggestion": suggestion,
        "explanation": explanation,
        "rule": rule,
    })


def apply_context_rules(text: str, issues):
    """Handle a few high-value learner-English patterns before LanguageTool.

    These are structural patterns, not sentence-specific fixes. They mainly help
    with omitted forms of 'be' that LanguageTool cannot always infer from context.
    """
    corrected = text

    # "my name Sourish" -> "my name is Sourish"
    pattern = r"\b(my\s+name)\s+([A-Za-z][A-Za-z'-]*)\b"
    for match in list(re.finditer(pattern, corrected, re.IGNORECASE)):
        name = match.group(2)
        if name.lower() in {"is", "was", "has"}:
            continue
        original = match.group(0)
        suggestion = f"{match.group(1)} is {name}"
        add_issue(
            issues, "grammar", original, suggestion,
            "Use 'is' in the expression 'my name is ...'.",
            "POLYWRITE_MISSING_BE",
        )
        corrected = corrected.replace(original, suggestion, 1)

    # "I Kamal from Vellore" / "I am Kamal from Vellore"
    # The first form is common learner English: subject + name + from-place.
    pattern = r"\b(i)\s+([A-Za-z][A-Za-z'-]*)\s+from\s+([A-Za-z][A-Za-z'-]*)\b"
    for match in list(re.finditer(pattern, corrected, re.IGNORECASE)):
        original = match.group(0)
        subject, name, place = match.groups()
        if name.lower() in {"am", "was", "have", "live"}:
            continue
        suggestion = f"{subject} am {name} from {place}"
        add_issue(
            issues, "grammar", original, suggestion,
            "Use 'am' after I when introducing yourself and stating where you are from.",
            "POLYWRITE_MISSING_BE",
        )
        corrected = corrected.replace(original, suggestion, 1)

    # "he/she Name from Place" -> "he/she is Name from Place"
    pattern = r"\b(he|she)\s+([A-Za-z][A-Za-z'-]*)\s+from\s+([A-Za-z][A-Za-z'-]*)\b"
    for match in list(re.finditer(pattern, corrected, re.IGNORECASE)):
        original = match.group(0)
        subject, name, place = match.groups()
        if name.lower() in {"is", "was", "has"}:
            continue
        suggestion = f"{subject} is {name} from {place}"
        add_issue(
            issues, "grammar", original, suggestion,
            "Use 'is' after he/she when introducing someone and stating where they are from.",
            "POLYWRITE_MISSING_BE",
        )
        corrected = corrected.replace(original, suggestion, 1)

    return corrected


def analyze_english(text: str):
    issues = []
    corrected = apply_context_rules(text, issues)

    # Protect known proper nouns while LanguageTool analyzes the rest.
    protected, replacements = protect_proper_nouns(corrected)
    matches = tool.check(protected)
    language_corrected = language_tool_python.utils.correct(protected, matches)
    language_corrected = restore_proper_nouns(language_corrected, replacements)

    # Convert LanguageTool matches into PolyWrite's unified issue format.
    for match in matches:
        original = protected[match.offset:match.offset + match.errorLength]
        replacement = match.replacements[0] if match.replacements else ""
        if not replacement:
            continue
        if "POLYNAME" in original or "POLYNAME" in replacement:
            continue

        rule_id = getattr(match, "ruleId", "") or "LANGUAGETOOL"
        upper_rule = rule_id.upper()
        issue_type = "spelling" if any(
            marker in upper_rule for marker in ("SPELL", "MORFOLOGIK", "TYPOS")
        ) else "grammar"

        add_issue(
            issues,
            issue_type,
            original,
            preserve_case(original, replacement),
            match.message,
            rule_id,
        )

    corrected = language_corrected

    # Final universal capitalization cleanup.
    corrected = re.sub(
        r"(^|(?<=[.!?])\s+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        corrected,
    )
    corrected = re.sub(r"\bi\b", "I", corrected)

    # Capitalization corrections are already represented by LanguageTool in most
    # cases; don't create duplicate issues merely because we normalize the text.
    return issues, corrected


@app.get("/")
def root():
    return {"message": "PolyWrite API is running", "engine": "LanguageTool + PolyWrite context rules"}


@app.post("/analyze")
def analyze(request: TextRequest):
    text = request.text.strip()
    issues, corrected_text = analyze_english(text)

    grammar = [i for i in issues if i["type"] == "grammar"]
    spelling = [i for i in issues if i["type"] == "spelling"]
    clarity = [i for i in issues if i["type"] == "clarity"]

    word_count = len(re.findall(r"\b[\w']+\b", text))
    sentence_count = len([s for s in re.split(r"[.!?]+", text) if s.strip()])
    score = max(
        0,
        min(100, 100 - len(grammar) * 8 - len(spelling) * 5 - len(clarity) * 3),
    )

    return {
        "text": text,
        "corrected_text": corrected_text,
        "issues": issues,
        "counts": {
            "grammar": len(grammar),
            "spelling": len(spelling),
            "clarity": len(clarity),
            "total": len(issues),
        },
        "stats": {
            "words": word_count,
            "characters": len(text),
            "sentences": sentence_count,
        },
        "score": score,
        "message": "Analysis complete" if issues else "No issues found",
    }
