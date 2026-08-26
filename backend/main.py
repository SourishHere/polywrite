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
    "tomorow":"tomorrow","tommorow":"tomorrow","recieve":"receive","untill":"until","thier":"their","freind":"friend",
    "arguement":"argument","comming":"coming","wich":"which","writting":"writing","seperately":"separately"
}

PAST_RULES = [
    (r"\b(he|she|it|I|you|we|they) go\b(?=\s+(?:yesterday|last\b|ago\b))", "went", "Use the past tense 'went' with a past-time expression."),
    (r"\b(he|she|it|I|you|we|they) eat\b(?=\s+(?:yesterday|last\b|ago\b))", "ate", "Use the past tense 'ate' with a past-time expression."),
    (r"\b(he|she|it|I|you|we|they) see\b(?=\s+(?:yesterday|last\b|ago\b))", "saw", "Use the past tense 'saw' with a past-time expression."),
    (r"\b(he|she|it|I|you|we|they) come\b(?=\s+(?:yesterday|last\b|ago\b))", "came", "Use the past tense 'came' with a past-time expression."),
    (r"\b(he|she|it|I|you|we|they) have\b(?=\s+(?:yesterday|last\b|ago\b))", "had", "Use the past tense 'had' with a past-time expression."),
]

GRAMMAR_RULES = [
    (r"\b(I) is\b", "am", "Use 'am' with I."),
    (r"\b(I|you|we|they) is\b", "are", "Use 'are' with I/you/we/they."),
    (r"\b(he|she|it) are\b", "is", "Use 'is' with he/she/it."),
    (r"\b(he|she|it) go\b", "goes", "Use 'goes' with he/she/it in the present tense."),
    (r"\b(he|she|it) do\b", "does", "Use 'does' with he/she/it in the present tense."),
    (r"\b(he|she|it) have\b", "has", "Use 'has' with he/she/it."),
    (r"\b(he|she|it) don't\b", "doesn't", "Use 'doesn't' with he/she/it."),
    (r"\b(I|you|we|they) doesn't\b", "don't", "Use 'don't' with I/you/we/they."),
    (r"\b(he|she|it) were\b", "was", "Use 'was' with he/she/it."),
    (r"\b(I|he|she|it) were\b", "was", "Use 'was' with a singular subject."),
    (r"\b(you|we|they) was\b", "were", "Use 'were' with you/we/they."),
    (r"\b(I|you|we|they) has\b", "have", "Use 'have' with I/you/we/they."),
    (r"\b(a)\s+([aeiouAEIOU][\w']*)", None, "Use 'an' before a vowel sound."),
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
            suggestion = f"{subject} {replacement}"
            key = (original.lower(), suggestion.lower())
            if key not in used:
                used.add(key)
                issues.append({"type":"grammar","original":original,"suggestion":suggestion,"explanation":explanation})
                corrected = corrected.replace(original, suggestion, 1)

    for pattern, replacement, explanation in GRAMMAR_RULES:
        match = re.search(pattern, corrected, re.IGNORECASE)
        if not match: continue
        original = match.group(0)
        if replacement is None:
            article, next_word = match.group(1), match.group(2)
            suggestion = "an " + next_word
            start = match.start()
            corrected = corrected[:start] + suggestion + corrected[match.end():]
        else:
            wrong_verb = original.split()[-1]
            suggestion = re.sub(re.escape(wrong_verb), replacement_case(wrong_verb, replacement), original, count=1, flags=re.IGNORECASE)
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
    total = len(issues)
    score = max(0, min(100, 100 - grammar.__len__()*8 - spelling.__len__()*5 - clarity.__len__()*3))
    return {
        "text":text,"corrected_text":corrected_text,"issues":issues,
        "counts":{"grammar":len(grammar),"spelling":len(spelling),"clarity":len(clarity),"total":total},
        "stats":{"words":word_count,"characters":len(text),"sentences":sentence_count},
        "score":score,
        "message":"Analysis complete" if issues else "No issues found"
    }
