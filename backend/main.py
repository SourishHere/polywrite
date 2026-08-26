from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
import logging
import language_tool_python

from local_grammar_model import improve_text

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


# LanguageTool provides detailed local grammar/spelling/punctuation detection.
tool = language_tool_python.LanguageTool("en-US")

PROPER_NOUNS = {
    "sourish": "Sourish", "kamal": "Kamal", "vellore": "Vellore",
    "chennai": "Chennai", "bangalore": "Bangalore", "bengaluru": "Bengaluru",
    "hyderabad": "Hyderabad", "tamil nadu": "Tamil Nadu", "india": "India",
    "vit": "VIT", "java": "Java", "python": "Python", "javascript": "JavaScript",
}


def protect_proper_nouns(text: str):
    protected = text
    replacements = {}
    for index, (name, proper) in enumerate(sorted(PROPER_NOUNS.items(), key=lambda x: -len(x[0]))):
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
    if not original or not suggestion or original.lower() == suggestion.lower():
        return
    key = (issue_type, original.lower(), suggestion.lower())
    if any((i["type"], i["original"].lower(), i["suggestion"].lower()) == key for i in issues):
        return
    issues.append({
        "type": issue_type, "original": original, "suggestion": suggestion,
        "explanation": explanation, "rule": rule,
    })


def apply_context_rules(text: str, issues):
    corrected = text

    # High-value structural learner-English patterns. These are intentionally
    # generic; they are not one-off sentence fixes.
    patterns = [
        (r"\b(my\s+name)\s+([A-Za-z][A-Za-z'-]*)\b",
         lambda m: f"{m.group(1)} is {m.group(2)}",
         "Use 'is' in the expression 'my name is ...'."),
        (r"\b(i)\s+([A-Za-z][A-Za-z'-]*)\s+from\s+([A-Za-z][A-Za-z'-]*)\b",
         lambda m: f"{m.group(1)} am {m.group(2)} from {m.group(3)}",
         "Use 'am' after I when introducing yourself and stating where you are from."),
        (r"\b(he|she)\s+([A-Za-z][A-Za-z'-]*)\s+from\s+([A-Za-z][A-Za-z'-]*)\b",
         lambda m: f"{m.group(1)} is {m.group(2)} from {m.group(3)}",
         "Use 'is' after he/she when introducing someone and stating where they are from."),
    ]

    for pattern, make_suggestion, explanation in patterns:
        for match in list(re.finditer(pattern, corrected, re.IGNORECASE)):
            original = match.group(0)
            suggestion = make_suggestion(match)
            if original.lower() == suggestion.lower():
                continue
            add_issue(issues, "grammar", original, suggestion, explanation, "POLYWRITE_MISSING_BE")
            corrected = corrected.replace(original, suggestion, 1)

    return corrected


def analyze_english(text: str):
    issues = []
    corrected = apply_context_rules(text, issues)

    # Run the local Transformer correction model first. If it is unavailable,
    # this simply returns the input and LanguageTool remains fully functional.
    protected, replacements = protect_proper_nouns(corrected)
    model_corrected = improve_text(protected)
    model_corrected = restore_proper_nouns(model_corrected, replacements)

    # Verify the model output with LanguageTool. If the model produces a clearly
    # worse result, keep the LanguageTool/local result rather than blindly using it.
    lt_input = model_corrected if model_corrected else corrected
    protected_lt, replacements_lt = protect_proper_nouns(lt_input)
    matches = tool.check(protected_lt)
    lt_corrected = language_tool_python.utils.correct(protected_lt, matches)
    lt_corrected = restore_proper_nouns(lt_corrected, replacements_lt)

    # Prefer the Transformer output when it changed the text; LanguageTool then
    # supplies transparent issue detection. If the model did nothing, LT corrects.
    corrected = model_corrected if model_corrected and model_corrected != protected else corrected
    if corrected == protected:
        corrected = corrected
    corrected = restore_proper_nouns(corrected, replacements)

    for match in matches:
        original = protected_lt[match.offset:match.offset + match.errorLength]
        replacement = match.replacements[0] if match.replacements else ""
        if not replacement or "POLYNAME" in original or "POLYNAME" in replacement:
            continue
        rule_id = getattr(match, "ruleId", "") or "LANGUAGETOOL"
        upper = rule_id.upper()
        issue_type = "spelling" if any(x in upper for x in ("SPELL", "MORFOLOGIK", "TYPO")) else "grammar"
        add_issue(
            issues, issue_type, original, preserve_case(original, replacement),
            match.message, rule_id,
        )

    corrected = re.sub(r"(^|(?<=[.!?])\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), corrected)
    corrected = re.sub(r"\bi\b", "I", corrected)
    return issues, corrected


@app.get("/")
def root():
    return {"message": "PolyWrite API is running", "engine": "Local Transformer + LanguageTool"}


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
