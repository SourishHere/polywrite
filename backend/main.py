from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
import language_tool_python

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

# LanguageTool provides the broad English grammar/spelling/style engine.
tool = language_tool_python.LanguageTool("en-US")

# Words that should be preserved as proper nouns. This prevents English spellcheck
# from changing names and places such as Vellore into unrelated English words.
PROPER_NOUNS = {
    "sourish": "Sourish",
    "vellore": "Vellore",
    "india": "India",
    "chennai": "Chennai",
    "tamil nadu": "Tamil Nadu",
    "vit": "VIT",
    "java": "Java",
    "python": "Python",
}

# High-confidence irregular forms used by learners.
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


def custom_rules(text):
    issues = []
    corrected = text

    # Missing forms of BE and common subject/verb agreement.
    rules = [
        (r"\b(I)\s+from\s+([A-Za-z]+)\b", lambda m: f"{m.group(1)} am from {m.group(2)}", "Use 'am' after I when stating where you are from."),
        (r"\b(he|she|it)\s+from\s+([A-Za-z]+)\b", lambda m: f"{m.group(1)} is from {m.group(2)}", "Use 'is' after he/she/it when stating where someone is from."),
        (r"\b(I)\s+a\s+([A-Za-z]+)\b", lambda m: f"{m.group(1)} am a {m.group(2)}", "Use 'am' after I."),
        (r"\b(he|she|it)\s+a\s+([A-Za-z]+)\b", lambda m: f"{m.group(1)} is a {m.group(2)}", "Use 'is' after he/she/it."),
        (r"\bmy\s+name\s+([A-Za-z]+)\b", lambda m: f"my name is {m.group(1)}", "Use 'is' in the expression 'my name is ...'."),
        (r"\b(he|she|it)\s+dont\b", lambda m: f"{m.group(1)} doesn't", "Use 'doesn't' with he/she/it."),
        (r"\b(I|you|we|they)\s+dont\b", lambda m: f"{m.group(1)} don't", "Use 'don't' with I/you/we/they."),
        (r"\b(he|she|it)\s+doesnt\b", lambda m: f"{m.group(1)} doesn't", "Use the apostrophe in 'doesn't'."),
        (r"\b(I|you|we|they)\s+doesnt\b", lambda m: f"{m.group(1)} don't", "Use 'don't' with I/you/we/they."),
        (r"\b(he|she|it)\s+have\b", lambda m: f"{m.group(1)} has", "Use 'has' with he/she/it."),
        (r"\b(I|you|we|they)\s+has\b", lambda m: f"{m.group(1)} have", "Use 'have' with I/you/we/they."),
        (r"\b(he|she|it)\s+do\b", lambda m: f"{m.group(1)} does", "Use 'does' with he/she/it."),
        (r"\b(I|you|we|they)\s+does\b", lambda m: f"{m.group(1)} do", "Use 'do' with I/you/we/they."),
        (r"\b(he|she|it)\s+were\b", lambda m: f"{m.group(1)} was", "Use 'was' with he/she/it."),
        (r"\b(I|you|we|they)\s+was\b", lambda m: f"{m.group(1)} were", "Use 'were' with I/you/we/they."),
        (r"\b(he|she|it)\s+go\b", lambda m: f"{m.group(1)} goes", "Use 'goes' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+like\b", lambda m: f"{m.group(1)} likes", "Use 'likes' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+play\b", lambda m: f"{m.group(1)} plays", "Use 'plays' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+work\b", lambda m: f"{m.group(1)} works", "Use 'works' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+eat\b", lambda m: f"{m.group(1)} eats", "Use 'eats' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+want\b", lambda m: f"{m.group(1)} wants", "Use 'wants' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+need\b", lambda m: f"{m.group(1)} needs", "Use 'needs' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+study\b", lambda m: f"{m.group(1)} studies", "Use 'studies' with he/she/it in the present tense."),
        (r"\b(he|she|it)\s+do not\b", lambda m: f"{m.group(1)} does not", "Use 'does not' with he/she/it."),
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
            "type": "grammar",
            "original": original,
            "suggestion": suggestion,
            "explanation": explanation,
            "rule": "POLYWRITE_CUSTOM_GRAMMAR",
        })
        corrected = corrected[:match.start()] + suggestion + corrected[match.end():]

    # Plural after common quantifiers. Only apply to words where pluralization is
    # reasonably safe; do not blindly turn uncountable nouns into plurals.
    quantifier_pattern = r"\b(many|several|few|these|those|two|three|four|five)\s+([A-Za-z]+)\b"
    for match in list(re.finditer(quantifier_pattern, corrected, re.IGNORECASE)):
        quantity, noun = match.group(1), match.group(2)
        lower = noun.lower()
        if lower in {"information", "advice", "money", "water", "furniture", "equipment", "news", "homework", "work"}:
            continue
        if lower.endswith("s"):
            continue
        plural = IRREGULAR_PLURALS.get(lower)
        if plural is None:
            if lower.endswith(("s", "x", "z", "ch", "sh")):
                plural = lower + "es"
            elif lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
                plural = lower[:-1] + "ies"
            else:
                plural = lower + "s"
        plural = preserve_case(noun, plural)
        original = match.group(0)
        suggestion = f"{quantity} {plural}"
        if suggestion.lower() == original.lower():
            continue
        issues.append({
            "type": "grammar",
            "original": original,
            "suggestion": suggestion,
            "explanation": f"Use the plural form '{plural}' after '{quantity}'.",
            "rule": "POLYWRITE_PLURAL_QUANTIFIER",
        })
        corrected = corrected[:match.start()] + suggestion + corrected[match.end():]

    # Sentence starts and the pronoun I are capitalization issues, but they should
    # not be reported as spelling errors.
    def capitalize_sentence(match):
        return match.group(1) + match.group(2).upper()

    corrected = re.sub(r"(^|(?<=[.!?])\s+)([a-z])", capitalize_sentence, corrected)
    corrected = re.sub(r"\bi\b", "I", corrected)
    return issues, corrected


def analyze_english(text: str):
    custom_issues, custom_corrected = custom_rules(text)

    # Protect known names/places before LanguageTool sees them.
    protected, replacements = protect_names(custom_corrected)
    matches = tool.check(protected)
    corrected = language_tool_python.utils.correct(protected, matches)
    corrected = restore_names(corrected, replacements)
    corrected = re.sub(r"\bi\b", "I", corrected)

    issues = custom_issues[:]
    for match in matches:
        original = protected[match.offset:match.offset + match.errorLength]
        replacement = match.replacements[0] if match.replacements else ""
        if not replacement or "POLYNAME" in original or "POLYNAME" in replacement:
            continue

        rule_id = getattr(match, "ruleId", "") or ""
        category = str(getattr(match, "category", "") or "").upper()
        rule_upper = rule_id.upper()
        if "MORFOLOGIK" in rule_upper or "TYPOS" in category or "SPELL" in rule_upper:
            issue_type = "spelling"
        elif "STYLE" in category or "STYLE" in rule_upper or "REDUND" in rule_upper:
            issue_type = "clarity"
        else:
            issue_type = "grammar"

        issues.append({
            "type": issue_type,
            "original": original,
            "suggestion": preserve_case(original, replacement),
            "explanation": match.message,
            "rule": rule_id,
        })

    # Add capitalization findings that are safe and useful to learners.
    for match in re.finditer(r"(^|(?<=[.!?])\s+)([a-z])", text):
        original = match.group(2)
        issues.append({
            "type": "grammar",
            "original": original,
            "suggestion": original.upper(),
            "explanation": "Start a sentence with a capital letter.",
            "rule": "POLYWRITE_SENTENCE_CAPITALIZATION",
        })

    for match in re.finditer(r"\bi\b", text):
        issues.append({
            "type": "grammar",
            "original": "i",
            "suggestion": "I",
            "explanation": "The personal pronoun 'I' should be uppercase.",
            "rule": "POLYWRITE_I_CAPITALIZATION",
        })

    # Long sentences are a clarity suggestion rather than a hard error.
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

    # De-duplicate overlapping findings.
    unique = []
    seen = set()
    for issue in issues:
        key = (issue["type"], issue["original"].lower(), issue["suggestion"].lower())
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

    # Score is an indicator, not a claim that the text is objectively perfect.
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
