from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
import logging
import os
import json
import urllib.request
import urllib.error
import urllib.parse
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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

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
    issues.append({"type": issue_type, "original": original, "suggestion": suggestion, "explanation": explanation, "rule": rule})


def apply_context_rules(text: str, issues):
    corrected = text
    pattern = r"\b(my\s+name)\s+(?!is\b|was\b|has\b)([A-Za-z][A-Za-z'-]*)\b"
    for match in list(re.finditer(pattern, corrected, re.IGNORECASE)):
        original = match.group(0)
        suggestion = f"{match.group(1)} is {match.group(2)}"
        add_issue(issues, "grammar", original, suggestion, "Use 'is' in the expression 'my name is ...'.", "POLYWRITE_MISSING_BE")
        corrected = corrected.replace(original, suggestion, 1)
    patterns = [
        (r"\b(i)\s+([A-Za-z][A-Za-z'-]*)\s+from\s+([A-Za-z][A-Za-z'-]*)\b", lambda m: f"{m.group(1)} am {m.group(2)} from {m.group(3)}", "Use 'am' after I when introducing yourself and stating where you are from."),
        (r"\b(he|she)\s+([A-Za-z][A-Za-z'-]*)\s+from\s+([A-Za-z][A-Za-z'-]*)\b", lambda m: f"{m.group(1)} is {m.group(2)} from {m.group(3)}", "Use 'is' after he/she when introducing someone and stating where they are from."),
    ]
    for pattern, make_suggestion, explanation in patterns:
        for match in list(re.finditer(pattern, corrected, re.IGNORECASE)):
            original, suggestion = match.group(0), make_suggestion(match)
            if original.lower() == suggestion.lower():
                continue
            add_issue(issues, "grammar", original, suggestion, explanation, "POLYWRITE_MISSING_BE")
            corrected = corrected.replace(original, suggestion, 1)
    return corrected


def call_gemini(text: str):
    if not GEMINI_API_KEY:
        return None, []
    prompt = """You are PolyWrite, a professional English grammar and writing assistant.
Correct the user's text while preserving the original meaning, names, places, technical terms, tone, and paragraph structure.
Fix grammar, spelling, punctuation, capitalization, word choice when clearly incorrect, and awkward sentence construction.
Do not invent facts or rewrite correct sentences unnecessarily.
Return ONLY valid JSON with this exact shape:
{"corrected_text":"...","issues":[{"type":"grammar|spelling|clarity","original":"...","suggestion":"...","explanation":"..."}]}
Each issue must correspond to a real change from the user's text. Keep issues concise and do not report mere stylistic preferences as errors.

User text:
""" + text
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
    }
    data = json.dumps(payload).encode("utf-8")
    url = GEMINI_URL.format(model=GEMINI_MODEL) + "?key=" + urllib.parse.quote(GEMINI_API_KEY, safe="")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        raw = body["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(raw)
        corrected = str(result.get("corrected_text", "")).strip()
        llm_issues = result.get("issues", [])
        return (corrected, llm_issues if isinstance(llm_issues, list) else []) if corrected else (None, [])
    except Exception as exc:
        logger.warning("Gemini unavailable; using local engine: %s", exc)
        return None, []


def add_model_differences(original: str, corrected: str, issues):
    if not corrected or original.strip() == corrected.strip():
        return
    old_words = re.findall(r"\b[\w']+\b", original)
    new_words = re.findall(r"\b[\w']+\b", corrected)
    matcher = SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old, new = " ".join(old_words[i1:i2]), " ".join(new_words[j1:j2])
        if not old or not new or old.lower() == new.lower():
            continue
        if old.lower() in PROPER_NOUNS and new.lower() == PROPER_NOUNS[old.lower()].lower():
            continue
        issue_type = "spelling" if len(old.split()) == 1 and len(new.split()) == 1 else "grammar"
        add_issue(issues, issue_type, old, new, "Possible spelling mistake." if issue_type == "spelling" else "Grammar or sentence-structure correction suggested.", "POLYWRITE_MODEL_CORRECTION")


def add_gemini_issues(issues, llm_issues, original):
    for item in llm_issues:
        if not isinstance(item, dict):
            continue
        issue_type = str(item.get("type", "grammar")).lower()
        if issue_type not in {"grammar", "spelling", "clarity"}:
            issue_type = "grammar"
        original_part = str(item.get("original", "")).strip()
        suggestion = str(item.get("suggestion", "")).strip()
        explanation = str(item.get("explanation", "Grammar correction.")).strip()
        if original_part and suggestion and original_part.lower() != suggestion.lower() and original_part.lower() in original.lower():
            add_issue(issues, issue_type, original_part, suggestion, explanation, "GEMINI")


def analyze_english(text: str):
    issues = []
    gemini_corrected, gemini_issues = call_gemini(text)
    if gemini_corrected:
        corrected = gemini_corrected
        add_gemini_issues(issues, gemini_issues, text)
        engine = "Gemini + LanguageTool"
    else:
        context_corrected = apply_context_rules(text, issues)
        protected_context, context_replacements = protect_proper_nouns(context_corrected)
        model_corrected = improve_text(protected_context)
        corrected = restore_proper_nouns(model_corrected, context_replacements)
        add_model_differences(text, corrected, issues)
        engine = "Local Transformer + LanguageTool"

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
        add_issue(issues, issue_type, restore_proper_nouns(original, replacements), preserve_case(original, replacement), match.message, rule_id)

    corrected = restore_proper_nouns(corrected, replacements)
    corrected = re.sub(r"(^|(?<=[.!?])\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), corrected)
    corrected = re.sub(r"\bi\b", "I", corrected)
    corrected = re.sub(r"\s+([,.!?])", r"\1", corrected)
    return issues, corrected, engine


@app.get("/")
def root():
    return {"message": "PolyWrite API is running", "engine": "Gemini + LanguageTool + local fallback", "gemini_enabled": bool(GEMINI_API_KEY)}


@app.post("/analyze")
def analyze(request: TextRequest):
    text = request.text.strip()
    issues, corrected_text, engine = analyze_english(text)
    grammar = [i for i in issues if i["type"] == "grammar"]
    spelling = [i for i in issues if i["type"] == "spelling"]
    clarity = [i for i in issues if i["type"] == "clarity"]
    word_count = len(re.findall(r"\b[\w']+\b", text))
    sentence_count = len([s for s in re.split(r"[.!?]+", text) if s.strip()])
    score = max(0, min(100, 100 - len(grammar) * 8 - len(spelling) * 5 - len(clarity) * 3))
    return {"text": text, "corrected_text": corrected_text, "issues": issues, "counts": {"grammar": len(grammar), "spelling": len(spelling), "clarity": len(clarity), "total": len(issues)}, "stats": {"words": word_count, "characters": len(text), "sentences": sentence_count}, "score": score, "engine": engine, "message": "Analysis complete" if issues else "No issues found"}
