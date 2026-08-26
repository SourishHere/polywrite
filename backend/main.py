from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
import language_tool_python

app = FastAPI(title="PolyWrite API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

class TextRequest(BaseModel):
    text: str

tool = language_tool_python.LanguageTool("en-US")

# Names and places that should not be treated as spelling mistakes.
PROPER_NOUNS = {
    "sourish": "Sourish", "vellore": "Vellore", "india": "India",
    "chennai": "Chennai", "tamil nadu": "Tamil Nadu", "vit": "VIT",
    "vit vellore": "VIT Vellore", "java": "Java", "python": "Python",
}


def protect_proper_nouns(text):
    protected = text
    placeholders = {}
    for index, (name, proper) in enumerate(sorted(PROPER_NOUNS.items(), key=lambda x: -len(x[0]))):
        placeholder = f"__POLYWRITE_NAME_{index}__"
        if re.search(r"\b" + re.escape(name) + r"\b", protected, re.IGNORECASE):
            protected = re.sub(r"\b" + re.escape(name) + r"\b", placeholder, protected, flags=re.IGNORECASE)
            placeholders[placeholder] = proper
    return protected, placeholders


def restore_proper_nouns(text, placeholders):
    for placeholder, proper in placeholders.items():
        text = text.replace(placeholder, proper)
    return text


def custom_analyze(text):
    issues = []
    corrected = text

    # Common learner omissions that a generic spell/grammar engine may miss.
    patterns = [
        (r"\bI\s+from\s+([A-Za-z]+)\b", lambda m: f"I am from {m.group(1)}", "Use 'am' after I."),
        (r"\b(he|she)\s+from\s+([A-Za-z]+)\b", lambda m: f"{m.group(1)} is from {m.group(2)}", "Use 'is' after he/she."),
        (r"\bI\s+a\s+([A-Za-z]+)\b", lambda m: f"I am a {m.group(1)}", "Use 'am' after I."),
        (r"\b(he|she)\s+a\s+([A-Za-z]+)\b", lambda m: f"{m.group(1)} is a {m.group(2)}", "Use 'is' after he/she."),
    ]
    for pattern, make_suggestion, explanation in patterns:
        match = re.search(pattern, corrected, re.IGNORECASE)
        if match:
            original = match.group(0)
            suggestion = make_suggestion(match)
            issues.append({"type": "grammar", "original": original, "suggestion": suggestion, "explanation": explanation, "rule": "POLYWRITE_MISSING_BE"})
            corrected = corrected[:match.start()] + suggestion + corrected[match.end():]

    # Capitalize sentence starts and the pronoun I.
    corrected = re.sub(r"(^|(?<=[.!?])\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), corrected)
    corrected = re.sub(r"\bi\b", "I", corrected)
    return issues, corrected


def analyze_english(text: str):
    custom_issues, custom_corrected = custom_analyze(text)
    protected, placeholders = protect_proper_nouns(custom_corrected)
    matches = tool.check(protected)
    issues = custom_issues[:]

    # Apply LanguageTool suggestions from right to left.
    corrected_protected = protected
    for match in sorted(matches, key=lambda m: m.offset, reverse=True):
        original = protected[match.offset:match.offset + match.errorLength]
        replacement = match.replacements[0] if match.replacements else ""
        rule_id = getattr(match, "ruleId", "") or ""
        category = getattr(match, "category", "") or ""
        if not replacement or "__POLYWRITE_NAME_" in original or "__POLYWRITE_NAME_" in replacement:
            continue
        category_upper = category.upper()
        if "TYPOS" in category_upper or "SPELL" in rule_id.upper() or "MORFOLOGIK" in rule_id.upper():
            issue_type = "spelling"
        elif "STYLE" in category_upper or "REDUND" in rule_id.upper():
            issue_type = "clarity"
        else:
            issue_type = "grammar"
        issues.append({"type": issue_type, "original": original, "suggestion": replacement, "explanation": match.message, "rule": rule_id})
        corrected_protected = corrected_protected[:match.offset] + replacement + corrected_protected[match.offset + match.errorLength:]

    corrected = restore_proper_nouns(corrected_protected, placeholders)

    # Protect custom fixes from accidental reversion and normalize known names.
    for name, proper in PROPER_NOUNS.items():
        corrected = re.sub(r"\b" + re.escape(name) + r"\b", proper, corrected, flags=re.IGNORECASE)

    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    for sentence in sentences:
        if len(re.findall(r"\b[\w']+\b", sentence)) > 35:
            issues.append({"type": "clarity", "original": "Long sentence", "suggestion": "Consider splitting this into shorter sentences.", "explanation": "Shorter sentences are usually easier to read.", "rule": "POLYWRITE_LONG_SENTENCE"})

    unique = []
    seen = set()
    for issue in issues:
        key = (issue["type"], issue["original"].lower(), issue["suggestion"].lower(), issue.get("rule", ""))
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique, corrected

@app.get("/")
def root():
    return {"message": "PolyWrite API is running", "engine": "LanguageTool + PolyWrite"}

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
    return {"text": text, "corrected_text": corrected_text, "issues": issues, "counts": {"grammar": len(grammar), "spelling": len(spelling), "clarity": len(clarity), "total": len(issues)}, "stats": {"words": word_count, "characters": len(text), "sentences": sentence_count}, "score": score, "message": "Analysis complete" if issues else "No issues found"}
