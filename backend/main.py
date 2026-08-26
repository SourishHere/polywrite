from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re

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


# Small, dependency-free spelling dictionary for the first version.
COMMON_MISSPELLINGS = {
    "teh": "the", "recieve": "receive", "seperate": "separate",
    "definately": "definitely", "occured": "occurred", "untill": "until",
    "becuase": "because", "alot": "a lot", "wich": "which",
    "langauge": "language", "grammer": "grammar", "wierd": "weird",
    "adress": "address", "enviroment": "environment", "succesful": "successful",
    "goverment": "government", "acheive": "achieve", "begining": "beginning",
}


def analyze_english(text: str):
    issues = []
    words = re.findall(r"\b[\w']+\b", text)

    # Common subject-verb agreement / tense patterns.
    grammar_rules = [
        (r"\b(I|you|we|they) is\b", "are", "Use 'are' with I/you/we/they."),
        (r"\b(he|she|it) are\b", "is", "Use 'is' with he/she/it."),
        (r"\b(he|she|it) go\b", "goes", "Use 'goes' with he/she/it in the present tense."),
        (r"\b(he|she|it) do\b", "does", "Use 'does' with he/she/it in the present tense."),
        (r"\b(he|she|it) have\b", "has", "Use 'has' with he/she/it."),
        (r"\b(he|she|it) was\b", "was", "This form is correct; check the surrounding sentence."),
    ]

    for pattern, replacement, explanation in grammar_rules:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and replacement != match.group(0).split()[-1].lower():
            wrong = match.group(0)
            corrected = re.sub(r"\b" + re.escape(wrong.split()[-1]) + r"\b", replacement, wrong, count=1, flags=re.IGNORECASE)
            issues.append({
                "type": "grammar",
                "original": wrong,
                "suggestion": corrected,
                "explanation": explanation,
            })

    # Past-time markers commonly require a past-tense verb.
    past_patterns = [
        (r"\b(he|she|it) go\b(?=\s+(yesterday|last|ago))", "went", "Use the past tense 'went' with a past-time expression."),
        (r"\b(I|you|we|they) go\b(?=\s+(yesterday|last|ago))", "went", "Use the past tense 'went' with a past-time expression."),
        (r"\b(he|she|it) eat\b(?=\s+(yesterday|last|ago))", "ate", "Use the past tense 'ate' with a past-time expression."),
        (r"\b(he|she|it) see\b(?=\s+(yesterday|last|ago))", "saw", "Use the past tense 'saw' with a past-time expression."),
        (r"\b(he|she|it) come\b(?=\s+(yesterday|last|ago))", "came", "Use the past tense 'came' with a past-time expression."),
    ]

    for pattern, replacement, explanation in past_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            original = match.group(0)
            subject = original.split()[0]
            corrected = f"{subject} {replacement}"
            issues.append({
                "type": "grammar",
                "original": original,
                "suggestion": corrected,
                "explanation": explanation,
            })

    # Spelling checks.
    seen_spelling = set()
    for word in words:
        lower = word.lower()
        if lower in COMMON_MISSPELLINGS and lower not in seen_spelling:
            seen_spelling.add(lower)
            issues.append({
                "type": "spelling",
                "original": word,
                "suggestion": COMMON_MISSPELLINGS[lower],
                "explanation": "Check the spelling of this word.",
            })

    # Basic clarity checks.
    if len(words) > 35:
        issues.append({
            "type": "clarity",
            "original": "Long sentence",
            "suggestion": "Consider splitting this into shorter sentences.",
            "explanation": "Shorter sentences are usually easier to read.",
        })

    if re.search(r"\b(very very|really really|basically basically)\b", text, re.IGNORECASE):
        issues.append({
            "type": "clarity",
            "original": "Repeated emphasis",
            "suggestion": "Remove the repeated word.",
            "explanation": "Avoid unnecessary repetition for clearer writing.",
        })

    corrected_text = text
    for issue in issues:
        if issue["type"] in ("grammar", "spelling"):
            corrected_text = corrected_text.replace(issue["original"], issue["suggestion"], 1)

    return issues, corrected_text


@app.get("/")
def root():
    return {"message": "PolyWrite API is running"}


@app.post("/analyze")
def analyze(request: TextRequest):
    text = request.text.strip()
    issues, corrected_text = analyze_english(text)
    grammar = [i for i in issues if i["type"] == "grammar"]
    spelling = [i for i in issues if i["type"] == "spelling"]
    clarity = [i for i in issues if i["type"] == "clarity"]

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
        "message": "Analysis complete" if issues else "No issues found",
    }
