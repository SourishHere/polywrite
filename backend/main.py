from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re

app = FastAPI(title="PolyWrite API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

class TextRequest(BaseModel):
    text: str

COMMON_MISSPELLINGS = {
    "teh":"the","recieve":"receive","seperate":"separate","definately":"definitely","occured":"occurred","untill":"until",
    "becuase":"because","alot":"a lot","wich":"which","langauge":"language","grammer":"grammar","wierd":"weird",
    "adress":"address","enviroment":"environment","succesful":"successful","goverment":"government","acheive":"achieve",
    "begining":"beginning","beleive":"believe","calender":"calendar","definate":"definite","occassion":"occasion",
    "tomorow":"tomorrow","tommorow":"tomorrow","thier":"their","freind":"friend","arguement":"argument",
    "comming":"coming","writting":"writing","seperately":"separately","recieve":"receive"
}

PAST_RULES = [
    (r"\b(he|she|it|I|you|we|they) go\b(?=\s+(?:yesterday|last\b|ago\b))", "went", "Use the past tense 'went' with a past-time expression."),
    (r"\b(he|she|it|I|you|we|they) eat\b(?=\s+(?:yesterday|last\b|ago\b))", "ate", "Use the past tense 'ate' with a past-time expression."),
    (r"\b(he|she|it|I|you|we|they) see\b(?=\s+(?:yesterday|last\b|ago\b))", "saw", "Use the past tense 'saw' with a past-time expression."),
    (r"\b(he|she|it|I|you|we|they) come\b(?=\s+(?:yesterday|last\b|ago\b))", "came", "Use the past tense 'came' with a past-time expression."),
    (r"\b(he|she|it|I|you|we|they) have\b(?=\s+(?:yesterday|last\b|ago\b))", "had", "Use the past tense 'had' with a past-time expression."),
]

GRAMMAR_RULES = [
    (r"\bI is\b", "am", "Use 'am' with I."),
    (r"\b(I|you|we|they) is\b", "are", "Use 'are' with I/you/we/they."),
    (r"\b(he|she|it) are\b", "is", "Use 'is' with he/she/it."),
    (r"\b(he|she|it) go\b", "goes", "Use 'goes' with he/she/it in the present tense."),
    (r"\b(he|she|it) do\b", "does", "Use 'does' with he/she/it in the present tense."),
    (r"\b(he|she|it) have\b", "has", "Use 'has' with he/she/it."),
    (r"\b(he|she|it) don't\b", "doesn't", "Use 'doesn't' with he/she/it."),
    (r"\b(he|she|it) dont\b", "doesn't", "Use 'doesn't' with he/she/it."),
    (r"\b(I|you|we|they) doesn't\b", "don't", "Use 'don't' with I/you/we/they."),
    (r"\b(I|you|we|they) doesnt\b", "don't", "Use 'don't' with I/you/we/they."),
    (r"\b(he|she|it) were\b", "was", "Use 'was' with he/she/it."),
    (r"\b(you|we|they) was\b", "were", "Use 'were' with you/we/they."),
    (r"\b(I|you|we|they) has\b", "have", "Use 'have' with I/you/we/they."),
    (r"\b(he|she|it) need\b", "needs", "Use 'needs' with he/she/it."),
    (r"\b(he|she|it) like\b", "likes", "Use 'likes' with he/she/it."),
    (r"\b(he|she|it) want\b", "wants", "Use 'wants' with he/she/it."),
    (r"\b(he|she|it) play\b", "plays", "Use 'plays' with he/she/it."),
    (r"\b(he|she|it) study\b", "studies", "Use 'studies' with he/she/it."),
]


def replacement_case(original, replacement):
    if original.isupper(): return replacement.upper()
    if original[:1].isupper(): return replacement.capitalize()
    return replacement


def analyze_english(text: str):
    issues = []
    words = re.findall(r"\b[\w']+\b", text)
    corrected = text
    used = set()

    for pattern, replacement, explanation in PAST_RULES:
        match = re.search(pattern, corrected, re.IGNORECASE)
        if match:
            original = match.group(0)
            subject = original.rsplit(" ", 1)[0]
            suggestion = f"{subject} {replacement_case(original.rsplit(' ',1)[-1], replacement)}"
            key = (original.lower(), suggestion.lower())
            if key not in used:
                used.add(key)
                issues.append({"type":"grammar","original":original,"suggestion":suggestion,"explanation":explanation})
                corrected = corrected.replace(original, suggestion, 1)

    for pattern, replacement, explanation in GRAMMAR_RULES:
        match = re.search(pattern, corrected, re.IGNORECASE)
        if not match: continue
        original = match.group(0)
        wrong_word = original.split()[-1]
        suggestion = re.sub(re.escape(wrong_word), replacement_case(wrong_word, replacement), original, count=1, flags=re.IGNORECASE)
        corrected = corrected.replace(original, suggestion, 1)
        key = (original.lower(), suggestion.lower())
        if key not in used:
            used.add(key)
            issues.append({"type":"grammar","original":original,"suggestion":suggestion,"explanation":explanation})

    seen = set()
    for word in words:
        lower = word.lower()
        if lower in COMMON_MISSPELLINGS and lower not in seen:
            seen.add(lower)
            suggestion = COMMON_MISSPELLINGS[lower]
            issues.append({"type":"spelling","original":word,"suggestion":suggestion,"explanation":"Check the spelling of this word."})
            corrected = re.sub(r"\b" + re.escape(word) + r"\b", suggestion, corrected, count=1, flags=re.IGNORECASE)

    # Simple countable-noun agreement checks.
    plural_triggers = ["many", "several", "few", "numerous", "two", "three", "four", "five"]
    for trigger in plural_triggers:
        match = re.search(r"\b" + trigger + r"\s+([a-zA-Z]+)\b", corrected, re.IGNORECASE)
        if match:
            noun = match.group(1)
            if noun.lower() in {"email", "book", "car", "student", "apple", "class", "problem", "idea", "question", "message", "day", "word", "sentence", "friend", "movie", "file"}:
                suggestion_noun = noun + ("es" if noun.lower().endswith(("s","x","z","ch","sh")) else "s")
                original = match.group(0)
                suggestion = f"{trigger} {suggestion_noun}"
                issues.append({"type":"grammar","original":original,"suggestion":suggestion,"explanation":f"Use the plural form '{suggestion_noun}' after '{trigger}'."})
                corrected = corrected[:match.start()] + suggestion + corrected[match.end():]

    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    for sentence in sentences:
        count = len(re.findall(r"\b[\w']+\b", sentence))
        if count > 35:
            issues.append({"type":"clarity","original":"Long sentence","suggestion":"Consider splitting this into shorter sentences.","explanation":"Shorter sentences are usually easier to read."})
    if re.search(r"\b(very very|really really|basically basically|just simply|each and every)\b", text, re.IGNORECASE):
        issues.append({"type":"clarity","original":"Repeated or redundant phrase","suggestion":"Remove unnecessary repetition.","explanation":"Concise wording makes writing clearer."})

    return issues, corrected

@app.get("/")
def root(): return {"message":"PolyWrite API is running"}

@app.post("/analyze")
def analyze(request: TextRequest):
    text = request.text.strip()
    issues, corrected_text = analyze_english(text)
    grammar = [i for i in issues if i["type"] == "grammar"]
    spelling = [i for i in issues if i["type"] == "spelling"]
    clarity = [i for i in issues if i["type"] == "clarity"]
    word_count = len(re.findall(r"\b[\w']+\b", text))
    sentence_count = len([s for s in re.split(r"[.!?]+", text) if s.strip()])
    score = max(0, min(100, 100 - len(grammar)*8 - len(spelling)*5 - len(clarity)*3))
    return {
        "text":text,"corrected_text":corrected_text,"issues":issues,
        "counts":{"grammar":len(grammar),"spelling":len(spelling),"clarity":len(clarity),"total":len(issues)},
        "stats":{"words":word_count,"characters":len(text),"sentences":sentence_count},
        "score":score,
        "message":"Analysis complete" if issues else "No issues found"
    }
