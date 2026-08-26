from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
import logging
from difflib import SequenceMatcher
import language_tool_python

from local_grammar_model import improve_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("polywrite")

app = FastAPI(title="PolyWrite API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

class TextRequest(BaseModel):
    text: str

tool = language_tool_python.LanguageTool("en-US")

PROPER_NOUNS = {
    "sourish": "Sourish", "kamal": "Kamal", "vellore": "Vellore",
    "chennai": "Chennai", "bangalore": "Bangalore", "bengaluru": "Bengaluru",
    "hyderabad": "Hyderabad", "tamil nadu": "Tamil Nadu", "india": "India",
    "vit": "VIT", "java": "Java", "python": "Python", "javascript": "JavaScript",
}


def protect_proper_nouns(text: str):
    protected, replacements = text, {}
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
        "type": issue_type,
        "original": original,
        "suggestion": suggestion,
        "explanation": explanation,
        "rule": rule,
    })


def apply_context_rules(text: str, issues):
    corrected = text

    pattern = r"\b(my\s+name)\s+(?!is\b|was\b|has\b)([A-Za-z][A-Za-z'-]*)\b"
    for match in list(re.finditer(pattern, corrected, re.IGNORECASE)):
        original = match.group(0)
        suggestion = f"{match.group(1)} is {match.group(2)}"
        add_issue(issues, "grammar", original, suggestion,
                  "Use 'is' in the expression 'my name is ...'.", "POLYWRITE_MISSING_BE")
        corrected = corrected.replace(original, suggestion, 1)

    patterns = [
        (r"\b(i)\s+([A-Za-z][A-Za-z'-]*)\s+from\s+([A-Za-z][A-Za-z'-]*)\b",
         lambda m: f"{m.group(1)} am {m.group(2)} from {m.group(3)}",
         "Use 'am' after I when introducing yourself and stating where you are from."),
        (r"\b(he|she)\s+([A-Za-z][A-Za-z'-]*)\s+from\s+([A-Za-z][A-Za-z'-]*)\b",
         lambda m: f"{m.group(1)} is {m.group(2)} from {m.group(3)}",
         "Use 'is' after he/she when introducing someone and stating where they are from."),
    ]
    for pattern, make_suggestion, explanation in patterns:
        for match in list(re.finditer(pattern, corrected, re.IGNORECASE)):
            original, suggestion = match.group(0), make_suggestion(match)
            if original.lower() == suggestion.lower():
                continue
            add_issue(issues, "grammar", original, suggestion, explanation, "POLYWRITE_MISSING_BE")
            corrected = corrected.replace(original, suggestion, 1)
    return corrected


def add_model_differences(original: str, corrected: str, issues):
    """Turn meaningful model corrections into Grammarly-style issue entries.

    LanguageTool is excellent for explicit rule matches, while the local T5
    model can fix errors that LanguageTool misses. Comparing the original and
    final text ensures those model-only corrections are still visible to the UI.
    """
    if not corrected or original.strip() == corrected.strip():
        return

    # Compare words rather than characters so an entire correction such as
    # "go" -> "went" or "he dont likes" -> "he doesn't like" is one issue.
    old_words = re.findall(r"\b[\w']+\b", original)
    new_words = re.findall(r"\b[\w']+\b", corrected)
    matcher = SequenceMatcher(a=old_words, b=new_words, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old = " ".join(old_words[i1:i2])
        new = " ".join(new_words[j1:j2])
        if not old or not new or old.lower() == new.lower():
            continue

        # Avoid adding noisy entries for proper-noun capitalization that we
        # intentionally normalize (Sourish/Vellore/Kamal, etc.).
        if old.lower() in PROPER_NOUNS and new.lower() == PROPER_NOUNS[old.lower()].lower():
            continue

        issue_type = "spelling" if len(old.split()) == 1 and len(new.split()) == 1 else "grammar"
        explanation = (
            "Possible spelling mistake." if issue_type == "spelling"
            else "Grammar or sentence-structure correction suggested."
        )
        add_issue(issues, issue_type, old, new, explanation, "POLYWRITE_MODEL_CORRECTION")


def analyze_english(text: str):
    issues = []

    # First apply small high-confidence PolyWrite rules. These are also used as
    # input to the local model so the model receives cleaner context.
    context_corrected = apply_context_rules(text, issues)

    # LanguageTool checks the ORIGINAL text, not an already corrected version.
    protected_original, replacements = protect_proper_nouns(text)
    matches = tool.check(protected_original)

    for match in matches:
        original = protected_original[match.offset:match.offset + match.errorLength]
        replacement = match.replacements[0] if match.replacements else ""
        if not replacement or "POLYNAME" in original or "POLYNAME" in replacement:
            continue
        rule_id = getattr(match, "ruleId", "") or "LANGUAGETOOL"
        upper = rule_id.upper()
        issue_type = "spelling" if any(x in upper for x in ("SPELL", "MORFOLOGIK", "TYPO")) else "grammar"
        add_issue(
            issues,
            issue_type,
            restore_proper_nouns(original, replacements),
            preserve_case(original, replacement),
            match.message,
            rule_id,
        )

    # The local Transformer provides the broad, natural-language correction.
    protected_context, context_replacements = protect_proper_nouns(context_corrected)
    model_corrected = improve_text(protected_context)
    corrected = restore_proper_nouns(model_corrected, context_replacements)

    # Capture corrections the model found that LanguageTool did not report.
    add_model_differences(text, corrected, issues)

    # Final presentation normalization.
    corrected = re.sub(
        r"(^|(?<=[.!?])\s+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        corrected,
    )
    corrected = re.sub(r"\bi\b", "I", corrected)
    corrected = re.sub(r"\s+([,.!?])", r"\1", corrected)
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
