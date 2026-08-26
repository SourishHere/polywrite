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

# Names/places that should not be treated as spelling mistakes.
PROPER_NOUNS = {
    "sourish": "Sourish", "vellore": "Vellore", "india": "India",
    "chennai": "Chennai", "tamil nadu": "Tamil Nadu", "vit": "VIT",
    "java": "Java", "python": "Python",
}


def protect_names(text):
    """Replace known names with safe alphabetic tokens, then restore them later."""
    protected = text
    replacements = {}
    for index, (name, proper) in enumerate(sorted(PROPER_NOUNS.items(), key=lambda x: -len(x[0]))):
        token = f"PolyName{index}X"
        pattern = r"\b" + re.escape(name) + r"\b"
        if re.search(pattern, protected, re.IGNORECASE):
            protected = re.sub(pattern, token, protected, flags=re.IGNORECASE)
            replacements[token] = proper
    return protected, replacements


def restore_names(text, replacements):
    for token, proper in replacements.items():
        text = re.sub(r"\b" + re.escape(token) + r"\b", proper, text)
    return text


def custom_rules(text):
    issues = []
    corrected = text

    rules = [
        (r"\bI\s+from\s+([A-Za-z]+)\b", lambda m: f"I am from {m.group(1)}", "Use 'am' after I when stating where you are from."),
        (r"\b(he|she)\s+from\s+([A-Za-z]+)\b", lambda m: f"{m.group(1)} is from {m.group(2)}", "Use 'is' after he/she when stating where someone is from."),
        (r"\bI\s+a\s+([A-Za-z]+)\b", lambda m: f"I am a {m.group(1)}", "Use 'am' after I."),
        (r"\b(he|she)\s+a\s+([A-Za-z]+)\b", lambda m: f"{m.group(1)} is a {m.group(2)}", "Use 'is' after he/she."),
        (r"\bmy\s+name\s+([A-Za-z]+)\b", lambda m: f"my name is {m.group(1)}", "Use 'is' in the expression 'my name is ...'."),
    ]

    for pattern, make_suggestion, explanation in rules:
        match = re.search(pattern, corrected, re.IGNORECASE)
        if match:
            original = match.group(0)
            suggestion = make_suggestion(match)
            # Preserve sentence-start capitalization.
            if original[0].isupper():
                suggestion = suggestion[0].upper() + suggestion[1:]
            issues.append({
                "type": "grammar",
                "original": original,
                "suggestion": suggestion,
                "explanation": explanation,
                "rule": "POLYWRITE_CUSTOM_GRAMMAR",
            })
            corrected = corrected[:match.start()] + suggestion + corrected[match.end():]

    # Capitalize sentence starts and the pronoun I before LanguageTool runs.
    corrected = re.sub(r"(^|(?<=[.!?])\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), corrected)
    corrected = re.sub(r"\bi\b", "I", corrected)
    return issues, corrected


def analyze_english(text: str):
    custom_issues, custom_corrected = custom_rules(text)

    # Protect known names/places from LanguageTool spelling corrections.
    protected, replacements = protect_names(custom_corrected)
    matches = tool.check(protected)
    corrected = language_tool_python.utils.correct(protected, matches)
    corrected = restore_names(corrected, replacements)

    issues = custom_issues[:]
    for match in matches:
        original = protected[match.offset:match.offset + match.errorLength]
        replacement = match.replacements[0] if match.replacements else ""
        if not replacement or "PolyName" in original or "PolyName" in replacement:
            continue

        rule_id = getattr(match, "ruleId", "") or ""
        category = (getattr(match, "category", "") or "").upper()
        if "TYPOS" in category or "SPELL" in rule_id.upper() or "MORFOLOGIK" in rule_id.upper() or "I_LOWERCASE" in rule_id.upper():
            issue_type = "spelling"
        elif "STYLE" in category or "STYLE" in rule_id.upper() or "REDUND" in rule_id.upper():
            issue_type = "clarity"
        else:
            issue_type = "grammar"

        issues.append({
            "type": issue_type,
            "original": original,
            "suggestion": replacement,
            "explanation": match.message,
            "rule": rule_id,
        })

    # Always restore/correct known proper nouns in the final output.
    corrected = restore_names(corrected, replacements)
    corrected = re.sub(r"\bi\b", "I", corrected)

    # Add clarity warning for very long sentences.
    for sentence in re.split(r"[.!?]+", text):
        if len(re.findall(r"\b[\w']+\b", sentence)) > 35:
            issues.append({
                "type": "clarity",
                "original": "Long sentence",
                "suggestion": "Consider splitting this into shorter sentences.",
                "explanation": "Shorter sentences are usually easier to read.",
                "rule": "POLYWRITE_LONG_SENTENCE",
            })
            break

    # Remove duplicate findings.
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
    return {"message": "PolyWrite API is running", "engine": "LanguageTool + PolyWrite rules"}


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
        "counts": {"grammar": len(grammar), "spelling": len(spelling), "clarity": len(clarity), "total": len(issues)},
        "stats": {"words": word_count, "characters": len(text), "sentences": sentence_count},
        "score": score,
        "message": "Analysis complete" if issues else "No issues found",
    }
