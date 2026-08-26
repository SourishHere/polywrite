from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
import language_tool_python

app = FastAPI(title="PolyWrite API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

class TextRequest(BaseModel):
    text: str

# LanguageTool provides the main English grammar, spelling, punctuation and style engine.
# The tool is initialized once so the local LanguageTool server can be reused between requests.
tool = language_tool_python.LanguageTool("en-US")


def analyze_english(text: str):
    matches = tool.check(text)
    issues = []
    corrected = text

    # Process from right to left so offsets remain valid while applying suggestions.
    for match in sorted(matches, key=lambda m: m.offset, reverse=True):
        original = text[match.offset:match.offset + match.errorLength]
        replacement = match.replacements[0] if match.replacements else ""
        category = getattr(match, "category", "") or ""
        rule_id = getattr(match, "ruleId", "") or ""
        category_upper = category.upper()

        if "TYPOS" in category_upper or "SPELL" in rule_id.upper():
            issue_type = "spelling"
        elif "STYLE" in category_upper or "STYLE" in rule_id.upper() or "REDUND" in rule_id.upper():
            issue_type = "clarity"
        else:
            issue_type = "grammar"

        issues.append({
            "type": issue_type,
            "original": original,
            "suggestion": replacement or "Review this phrase",
            "explanation": match.message,
            "rule": rule_id,
        })

        if replacement:
            corrected = corrected[:match.offset] + replacement + corrected[match.offset + match.errorLength:]

    issues.reverse()
    grammar = [i for i in issues if i["type"] == "grammar"]
    spelling = [i for i in issues if i["type"] == "spelling"]
    clarity = [i for i in issues if i["type"] == "clarity"]

    return issues, corrected


@app.get("/")
def root():
    return {"message": "PolyWrite API is running", "engine": "LanguageTool English"}


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
