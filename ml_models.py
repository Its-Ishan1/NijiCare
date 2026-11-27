#!/usr/bin/env python3
"""Zero-dependency pure-Python stdlib inference for Secret Wards hybrid ML models.

Provides:
1. LinearChainCRF — Exact Viterbi decoding + Forward-Backward marginal probabilities
   for free-text multilingual NER fallback (B/I-NAME, B/I-ADDRESS).
2. ColumnValueClassifier — Softmax multinomial logistic regression over value-level
   character n-grams & structural statistics for unseen CSV/TSV column headers.

Standard library only (Python 3.10+). Models load from gzipped JSON files in models/.
"""
from __future__ import annotations

import gzip
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- shared tokenization & cues
NER_TAGS = ("O", "B-NAME", "I-NAME", "B-ADDRESS", "I-ADDRESS")
NER_TAG_TO_ID = {t: i for i, t in enumerate(NER_TAGS)}

COL_CLASSES = ("NAME", "ADDRESS", "PHONE", "EMAIL", "MRN", "CLINICAL", "OTHER")

_TOKEN_RE = re.compile(
    r"\[[A-Z_]+\]"
    r"|[A-Za-z]+(?:\.[A-Za-z]+)*\.?"
    r"|[\u0900-\u097f]+(?:\u093c)?"
    r"|[0-9\u0966-\u096f]+(?:[./:-][0-9\u0966-\u096f]+)*"
    r"|[^\s]"
)

DOC_CUES = frozenset({
    "dr", "dr.", "doctor", "consultant", "physician", "prof", "prof.", "surgeon",
    "specialist", "attending", "reviewed", "prescriber", "clinician", "डॉ", "डॉ.", "डॉक्टर",
})

ADDR_CUES = frozenset({
    "near", "opp", "opp.", "opposite", "behind", "beside", "house", "h.no", "hno", "flat",
    "plot", "lane", "gali", "road", "rd", "rd.", "marg", "street", "st", "colony", "nagar",
    "vihar", "enclave", "sector", "mohalla", "basti", "gaon", "gram", "village", "vill",
    "post", "po", "tehsil", "tahsil", "block", "chowk", "bazar", "bazaar", "mandir",
    "masjid", "station", "stand", "residing", "resident", "lives", "living", "staying",
    "address", "pata", "niwasi", "locality", "landmark", "pin", "pincode",
    "निवासी", "ग्राम", "गाँव", "गांव", "मोहल्ला", "गली", "रोड", "मार्ग", "पास",
    "मकान", "पता", "नगर", "कॉलोनी", "बाजार", "चौक", "तहसील", "थाना", "पोस्ट",
})

NAME_LEAD_CUES = frozenset({
    "patient", "pt", "pt.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "shri", "smt", "smt.",
    "kumari", "km", "km.", "master", "baby", "brought", "accompanied", "attendant",
    "relative", "guardian", "spouse", "wife", "husband", "son", "daughter", "father",
    "mother", "brother", "sister", "caller", "visitor", "informant", "witness",
    "referred", "named", "name", "naam", "registrant", "beneficiary", "subject",
    "मरीज", "मरीज़", "रोगी", "श्री", "श्रीमती", "कुमारी", "पुत्र", "पुत्री",
    "पत्नी", "पति", "पिता", "माता", "परिजन", "तीमारदार", "नाम",
})

NAME_TRAIL_CUES = frozenset({
    "complained", "presents", "presented", "reported", "admitted", "discharged", "aged",
    "age", "years", "yrs", "yr", "male", "female", "came", "arrived", "called", "visited",
    "residing", "lives", "living", "from", "s/o", "d/o", "w/o", "c/o", "k/c/o", "h/o",
    "ji", "sahab", "didi", "bhai", "bhaiya", "behenji", "babu", "amma",
    "ka", "ki", "ke", "ko", "ne", "se", "hai", "hain",
    "को", "का", "की", "के", "ने", "से", "जी", "साहब", "उम्र", "आयु", "वर्ष", "साल",
})

CLINICAL_CUES = frozenset({
    "tab", "tab.", "cap", "cap.", "inj", "inj.", "syp", "syp.", "iv", "im", "sc", "po",
    "od", "bd", "tds", "tid", "qid", "sos", "stat", "hs", "mg", "mcg", "ug", "µg", "g",
    "gm", "ml", "dl", "ul", "mmhg", "bpm", "spo2", "bp", "hr", "rr", "temp", "pulse",
    "sugar", "rbs", "fbs", "hba1c", "cbc", "hb", "wbc", "rbc", "plt", "platelets", "platelet",
    "crp", "esr", "lft", "kft", "ecg", "xray", "x-ray", "usg", "ct", "mri", "icd", "rx", "dx",
    "o/e", "ward", "icu", "nicu", "picu", "opd", "ipd", "er", "bed", "dose", "dosage",
    "diagnosis", "fever", "cough", "chills", "vomiting", "diarrhea", "headache", "weakness",
    "pain", "dyspnea", "nausea", "edema", "jaundice", "rash", "bleeding", "seizure",
    "syndrome", "disease", "palsy", "lymphoma", "tumor", "tumour", "carcinoma", "sarcoma",
    "anemia", "anaemia", "malaria", "dengue", "typhoid", "enteric", "pneumonia", "bronchitis",
    "diabetes", "hypertension", "asthma", "tuberculosis", "tb", "gastroenteritis", "sepsis",
    "hepatitis", "chikungunya", "covid", "influenza", "uri", "uti", "copd", "cad", "ckd",
    "tablet", "capsule", "injection", "syrup", "saline", "ringer", "lactate", "ors", "zinc",
    "paracetamol", "amoxicillin", "azithromycin", "cefixime", "ceftriaxone", "metformin",
    "amlodipine", "atenolol", "losartan", "omeprazole", "pantoprazole", "cetirizine",
    "chloroquine", "doxycycline", "ciprofloxacin", "metronidazole", "ibuprofen", "aspirin",
    "insulin", "heparin", "warfarin", "atorvastatin", "clopidogrel", "ondansetron",
    "hospital", "clinic", "centre", "center", "department", "dept", "unit", "pharmacy",
    "laboratory", "lab", "pathology", "radiology", "asha", "anm", "nurse", "nursing",
    "medical", "surgical", "general", "medicine", "pediatrics", "obstetrics", "gynecology",
    "parkinson", "parkinson's", "hodgkin", "hodgkin's", "bell", "bell's", "alzheimer",
    "alzheimer's", "cushing", "cushing's", "graves", "addison", "addison's", "wilms",
    "crohn", "crohn's", "guillain", "barre", "stevens", "johnson", "kawasaki", "raynaud",
    "kala-azar", "kala", "azar", "vivax", "falciparum", "normal", "mild", "moderate",
    "severe", "acute", "chronic", "resolving", "stable", "afebrile", "conscious", "oriented",
    "बुखार", "खांसी", "दर्द", "जांच", "दवा", "इलाज", "अस्पताल", "वार्ड", "रिपोर्ट", "गोली",
})

STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "with", "without", "was", "were", "is", "are",
    "be", "been", "has", "have", "had", "not", "no", "but", "she", "her", "he", "his", "him",
    "they", "their", "this", "that", "these", "those", "into", "onto", "after", "before",
    "during", "since", "until", "days", "day", "weeks", "week", "months", "month", "hours",
    "hour", "history", "complaint", "complaints", "vitals", "labs", "plan", "advice",
    "review", "discharge", "admission", "note", "notes", "summary", "follow", "follow-up",
    "followup", "up", "today", "yesterday", "tomorrow", "morning", "evening", "night",
    "improving", "started", "continued", "stopped", "advised", "planned", "given", "done",
    "seen", "found", "noted", "present", "absent", "positive", "negative", "high", "low",
    "under", "care", "of", "in", "on", "to", "by", "as", "per", "for", "at", "via",
    "report", "callback", "record", "visit", "check", "test", "result", "results", "value",
    "है", "हैं", "था", "थी", "थे", "और", "तथा", "में", "पर", "लिए", "दिन", "दिनों",
    "भर्ती", "छुट्टी", "सामान्य", "स्थिर", "के", "बाद", "पहले", "आज", "कल",
})

CLOSED_FUNCTION_WORDS = DOC_CUES | ADDR_CUES | NAME_LEAD_CUES | NAME_TRAIL_CUES | CLINICAL_CUES | STOPWORDS

# Known clinical eponyms & non-PII capitalized phrases that ML must never redact
PROTECTED_CLINICAL_TERMS = frozenset({
    "parkinson", "parkinson's", "hodgkin", "hodgkin's", "bell's", "alzheimer", "alzheimer's",
    "cushing", "cushing's", "graves", "addison", "addison's", "wilms", "crohn", "crohn's",
    "guillain", "barre", "stevens", "johnson", "kawasaki", "raynaud", "marfan", "hashimoto",
    "burkitt", "ewing", "kaposi", "paget", "barrett", "meniere", "tourette", "huntington",
    "down", "turner", "klinefelter", "asperger", "sjogren", "behcet", "takayasu", "wegener",
    "normal saline", "ringer lactate", "ringers lactate", "dextrose normal", "oral rehydration",
    "blood pressure", "heart rate", "respiratory rate", "chest pain", "shortness breath",
    "community acquired", "enteric fever", "dengue fever", "vivax malaria", "falciparum malaria",
    "typhoid fever", "viral fever", "acute gastroenteritis", "iron deficiency", "urinary tract",
    "upper respiratory", "lower respiratory", "intensive care", "emergency room", "outpatient department",
    "general medicine", "general ward", "medical ward", "surgical ward", "female ward", "male ward",
    "pediatric ward", "maternity ward", "asha worker", "staff nurse", "duty doctor", "ward boy",
    "discharge summary", "clinical note", "follow up", "shift handoff", "lab report", "blood test",
    "complete blood", "liver function", "kidney function", "fasting blood", "random blood",
})


def tokenize_with_spans(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


def _script_class(tok: str) -> str:
    if tok.startswith("[") and tok.endswith("]"):
        return "tag"
    has_lat = any("A" <= c <= "Z" or "a" <= c <= "z" for c in tok)
    has_deva = any("\u0900" <= c <= "\u097f" for c in tok)
    has_dig = any(c.isdigit() for c in tok)
    if has_deva and not has_lat and not has_dig:
        return "deva"
    if has_lat and not has_deva and not has_dig:
        return "latin"
    if has_dig and not has_lat and not has_deva:
        return "digit"
    if has_lat or has_deva or has_dig:
        return "mixed"
    return "punct"


def _word_shape(tok: str) -> str:
    if tok.startswith("[") and tok.endswith("]"):
        return "TAG"
    if len(tok) == 2 and tok[0].isupper() and tok[1] == ".":
        return "INIT"
    if tok[0].isupper() and len(tok) > 1 and tok[1:].islower():
        return "Title"
    if tok.isupper() and any(c.isalpha() for c in tok):
        return "UPPER"
    if tok.islower():
        return "lower"
    if any(c.isdigit() for c in tok):
        return "DIG"
    return "OTHER"


def _len_bucket(tok: str) -> str:
    n = len(tok)
    if n <= 1:
        return "1"
    if n == 2:
        return "2"
    if n <= 4:
        return "3-4"
    if n <= 8:
        return "5-8"
    return "9+"


def _token_roles(tok: str) -> list[str]:
    low = tok.casefold()
    low_nodot = low.rstrip(".")
    roles = []
    if low in DOC_CUES or low_nodot in DOC_CUES:
        roles.append("doc")
    if low in ADDR_CUES or low_nodot in ADDR_CUES:
        roles.append("addr")
    if low in NAME_LEAD_CUES or low_nodot in NAME_LEAD_CUES:
        roles.append("nlead")
    if low in NAME_TRAIL_CUES or low_nodot in NAME_TRAIL_CUES:
        roles.append("ntrail")
    if low in CLINICAL_CUES or low_nodot in CLINICAL_CUES:
        roles.append("clin")
    if low in STOPWORDS:
        roles.append("stop")
    return roles


def crf_token_features(tokens: list[str], i: int) -> list[str]:
    """Extract strictly generalizable morphological & context features (NO raw proper nouns)."""
    tok = tokens[i]
    low = tok.casefold()
    scr = _script_class(tok)
    shp = _word_shape(tok)
    roles = _token_roles(tok)

    feats = [
        "bias",
        f"scr={scr}",
        f"shp={shp}",
        f"len={_len_bucket(tok)}",
        f"scr_shp={scr}_{shp}",
    ]
    for r in roles:
        feats.append(f"role={r}")
    if low in CLOSED_FUNCTION_WORDS:
        feats.append(f"cw={low}")
    elif scr == "punct":
        feats.append(f"punct={tok}")

    # Morphological affixes (for non-tag, non-digit words >= 3 chars)
    if scr in ("latin", "deva") and len(low) >= 3:
        feats.append(f"p2={low[:2]}")
        feats.append(f"s2={low[-2:]}")
        if len(low) >= 4:
            feats.append(f"p3={low[:3]}")
            feats.append(f"s3={low[-3:]}")
        if len(low) >= 5:
            feats.append(f"s4={low[-4:]}")

    if i == 0:
        feats.append("BOS")
    if i == len(tokens) - 1:
        feats.append("EOS")

    # Neighbor window: -2, -1, +1, +2
    for offset in (-2, -1, 1, 2):
        j = i + offset
        tag = f"o{offset:+d}"
        if 0 <= j < len(tokens):
            ntok = tokens[j]
            nlow = ntok.casefold()
            nscr = _script_class(ntok)
            nshp = _word_shape(ntok)
            nroles = _token_roles(ntok)
            feats.append(f"{tag}_scr={nscr}")
            feats.append(f"{tag}_shp={nshp}")
            for nr in nroles:
                feats.append(f"{tag}_role={nr}")
            if nlow in CLOSED_FUNCTION_WORDS:
                feats.append(f"{tag}_cw={nlow}")
            elif nscr == "punct":
                feats.append(f"{tag}_p={ntok}")
        else:
            feats.append(f"{tag}=BOUND")

    # Key interaction features (doctor guard, multi-word name chains, address chains)
    if i > 0:
        p1_shp = _word_shape(tokens[i - 1])
        p1_roles = _token_roles(tokens[i - 1])
        feats.append(f"bg_p1shp_cur={p1_shp}_{shp}")
        for pr in p1_roles:
            feats.append(f"bg_p1r_cur={pr}_{scr}_{shp}")
    if i > 1:
        p2_roles = _token_roles(tokens[i - 2])
        p1_shp = _word_shape(tokens[i - 1])
        if "doc" in p2_roles:
            feats.append(f"tg_doc_p1_cur={p1_shp}_{shp}")
        if "addr" in p2_roles:
            feats.append(f"tg_addr_p1_cur={p1_shp}_{shp}")
        if "nlead" in p2_roles:
            feats.append(f"tg_nlead_p1_cur={p1_shp}_{shp}")
    if i + 1 < len(tokens):
        n1_shp = _word_shape(tokens[i + 1])
        n1_roles = _token_roles(tokens[i + 1])
        feats.append(f"bg_cur_n1shp={shp}_{n1_shp}")
        for nr in n1_roles:
            feats.append(f"bg_cur_n1r={scr}_{shp}_{nr}")
    if i + 2 < len(tokens):
        n2_roles = _token_roles(tokens[i + 2])
        if "ntrail" in n2_roles:
            feats.append(f"tg_cur_n2trail={scr}_{shp}")

    return feats


# --------------------------------------------------------------------------- Model 1: Pure-Python Linear-Chain CRF
def _logsumexp(vals: list[float]) -> float:
    m = max(vals)
    if m == float("-inf"):
        return m
    return m + math.log(sum(math.exp(v - m) for v in vals))


class LinearChainCRF:
    """Exact Viterbi + Forward-Backward inference for a trained linear-chain CRF."""

    def __init__(self, payload: dict[str, Any]):
        self.tags: list[str] = payload["tags"]
        self.n_tags = len(self.tags)
        self.start: list[float] = payload["start"]
        self.end: list[float] = payload["end"]
        self.trans: list[list[float]] = payload["trans"]
        # Sparse feature -> [w_tag0, w_tag1, ...]
        self.weights: dict[str, list[float]] = payload["weights"]

    @classmethod
    def load(cls, path: Path) -> "LinearChainCRF":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return cls(json.load(f))

    def _emissions(self, tokens: list[str]) -> list[list[float]]:
        k = self.n_tags
        weights = self.weights
        emits: list[list[float]] = []
        for i in range(len(tokens)):
            scores = [0.0] * k
            for feat in crf_token_features(tokens, i):
                w = weights.get(feat)
                if w is not None:
                    for t in range(k):
                        scores[t] += w[t]
            emits.append(scores)
        return emits

    def predict_with_marginals(self, tokens: list[str]) -> tuple[list[str], list[float]]:
        n = len(tokens)
        if n == 0:
            return [], []
        k = self.n_tags
        emits = self._emissions(tokens)
        trans = self.trans

        # Viterbi decoding
        dp = [[self.start[t] + emits[0][t] for t in range(k)]]
        back: list[list[int]] = []
        for i in range(1, n):
            prev = dp[-1]
            cur = [0.0] * k
            bp = [0] * k
            ei = emits[i]
            for t in range(k):
                best_v = float("-inf")
                best_p = 0
                for p in range(k):
                    v = prev[p] + trans[p][t]
                    if v > best_v:
                        best_v = v
                        best_p = p
                cur[t] = best_v + ei[t]
                bp[t] = best_p
            dp.append(cur)
            back.append(bp)

        last_scores = [dp[-1][t] + self.end[t] for t in range(k)]
        best_last = max(range(k), key=lambda t: last_scores[t])
        path = [best_last]
        for bp in reversed(back):
            path.append(bp[path[-1]])
        path.reverse()

        # Forward-Backward log marginals
        alpha = [[self.start[t] + emits[0][t] for t in range(k)]]
        for i in range(1, n):
            prev = alpha[-1]
            ei = emits[i]
            cur = [_logsumexp([prev[p] + trans[p][t] for p in range(k)]) + ei[t] for t in range(k)]
            alpha.append(cur)
        log_z = _logsumexp([alpha[-1][t] + self.end[t] for t in range(k)])

        beta = [[0.0] * k for _ in range(n)]
        beta[-1] = list(self.end)
        for i in range(n - 2, -1, -1):
            nxt_b = beta[i + 1]
            nxt_e = emits[i + 1]
            beta[i] = [_logsumexp([trans[p][t] + nxt_e[t] + nxt_b[t] for t in range(k)]) for p in range(k)]

        tags = [self.tags[idx] for idx in path]
        probs = [math.exp(max(-30.0, min(0.0, alpha[i][path[i]] + beta[i][path[i]] - log_z))) for i in range(n)]
        return tags, probs

    def redact_prose(
        self,
        text: str,
        *,
        threshold: float = 0.85,
        redact_names: bool = True,
        redact_addresses: bool = True,
        preserve_doctors: bool = True,
    ) -> tuple[str, list[str]]:
        """Run CRF NER on free-text prose with strict confidence & clinical safety guards."""
        if not text or (not redact_names and not redact_addresses):
            return text, []
        spans = tokenize_with_spans(text)
        if len(spans) < 2:
            return text, []
        tokens = [s[0] for s in spans]
        tags, probs = self.predict_with_marginals(tokens)

        replacements: list[tuple[int, int, str]] = []
        i = 0
        n = len(tokens)
        while i < n:
            tag = tags[i]
            if tag not in ("B-NAME", "B-ADDRESS"):
                i += 1
                continue
            kind = "NAME" if tag == "B-NAME" else "ADDRESS"
            j = i + 1
            while j < n and tags[j] == f"I-{kind}":
                j += 1

            # Check enabled category
            if (kind == "NAME" and not redact_names) or (kind == "ADDRESS" and not redact_addresses):
                i = j
                continue

            span_tokens = tokens[i:j]
            span_probs = probs[i:j]
            mean_prob = sum(span_probs) / len(span_probs)
            start_char = spans[i][1]
            end_char = spans[j - 1][2]
            if kind == "ADDRESS":
                # CRF tokenization can stop at a comma inside a compound address,
                # leaving the locality (for example, "Near Grain Mandi, Mahmudabad")
                # visible. Absorb a short title-cased locality suffix after that comma.
                suffix = re.match(
                    r",\s+([A-Z][A-Za-z'’\-]*(?:\s+[A-Z][A-Za-z'’\-]*){0,2})(?=[.,;:]|\s|$)",
                    text[end_char:],
                )
                if suffix and not suffix.group(1).casefold().startswith(("dr ", "dr.")):
                    end_char += suffix.end(1)
            raw_span = text[start_char:end_char]
            low_span = raw_span.casefold().strip()

            # Strict clinical & precision safety guards
            if mean_prob < threshold:
                i = j
                continue
            # Never redact a key/field label preceding ':' or '=' (e.g. "Admit Date:", "एड्रेस पेशेंट का:")
            if any(t in (":", "：", "=") for t in tokens[j:min(n, j + 3)]):
                i = j
                continue
            if any(t.startswith("[") and t.endswith("]") for t in span_tokens):
                i = j
                continue
            # Require at least 2 words for bare NAME (prevents single-word false positives)
            word_tokens = [t for t in span_tokens if _script_class(t) in ("latin", "deva")]
            if kind == "NAME" and len(word_tokens) < 2:
                i = j
                continue
            if kind == "NAME" and any(
                t.casefold() in {"date", "name", "legal", "admit", "discharge", "chart", "beneficiary", "registrant", "patient", "reference", "summary", "note", "report"}
                for t in word_tokens
            ):
                i = j
                continue
            if kind == "ADDRESS" and len(span_tokens) < 2:
                i = j
                continue
            # Never redact doctors if preserve_doctors is on
            if kind == "NAME" and preserve_doctors:
                lookback = tokens[max(0, i - 3):i]
                if any(t.casefold().rstrip(".") in DOC_CUES for t in lookback):
                    i = j
                    continue
            # Never redact known clinical eponyms, drugs, doses, or clinical cue phrases
            if low_span in PROTECTED_CLINICAL_TERMS:
                i = j
                continue
            if any(t.casefold().rstrip(".") in CLINICAL_CUES for t in word_tokens):
                if kind == "NAME":
                    i = j
                    continue
                # For addresses, reject if dominated by clinical cues
                clin_hits = sum(1 for t in word_tokens if t.casefold().rstrip(".") in CLINICAL_CUES)
                if clin_hits >= max(1, len(word_tokens) // 2):
                    i = j
                    continue
            if kind == "NAME" and any(any(c.isdigit() for c in t) for t in span_tokens):
                i = j
                continue
            if all(t.casefold() in STOPWORDS for t in word_tokens):
                i = j
                continue

            replacements.append((start_char, end_char, kind))
            i = j

        if not replacements:
            return text, []

        pieces = []
        emitted_kinds = []
        cursor = 0
        for st, en, kind in replacements:
            if st < cursor:
                continue
            pieces.append(text[cursor:st])
            pieces.append(f"[{kind}]")
            emitted_kinds.append(kind)
            cursor = en
        pieces.append(text[cursor:])
        return "".join(pieces), emitted_kinds


# --------------------------------------------------------------------------- Model 2: Pure-Python Column-Value Classifier
_PHONE_VAL = re.compile(r"^(?:\+?(?:91|९१)[\s-]?)?[6-9\u096c-\u096f][0-9\u0966-\u096f]{4}[\s-]?[0-9\u0966-\u096f]{5}$")
_EMAIL_VAL = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
_MRN_VAL = re.compile(r"^[A-Z]{2,8}[-/]?(?:\d{2,4}[-/])?\d{4,12}$")
_DATE_VAL = re.compile(r"^(?:\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{4})$")
_MED_UNIT_VAL = re.compile(r"(?i)\b(?:\d+(?:\.\d+)?\s*(?:mg|mcg|ml|dl|ul|mmhg|bpm|%)|1-0-1|1-1-1|0-0-1|od|bd|tds|tid|qid|sos|tab\.?|cap\.?|inj\.?|syp\.?)\b")
_ICD_VAL = re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,2})?\b")
_DOC_VAL = re.compile(r"(?i)^(?:dr\.?|doctor|डॉ\.?)\s+")


def extract_column_features(values: list[str]) -> dict[str, float]:
    """Extract header-blind statistical & character n-gram features from column values."""
    clean = [v.strip() for v in values if v and v.strip()]
    if not clean:
        return {}
    n = len(clean)
    feats: dict[str, float] = {}

    # Structural ratios
    feats["f:phone_r"] = sum(1 for v in clean if _PHONE_VAL.match(v)) / n
    feats["f:email_r"] = sum(1 for v in clean if _EMAIL_VAL.match(v)) / n
    feats["f:mrn_r"] = sum(1 for v in clean if _MRN_VAL.match(v.upper())) / n
    feats["f:date_r"] = sum(1 for v in clean if _DATE_VAL.match(v)) / n
    feats["f:med_r"] = sum(1 for v in clean if _MED_UNIT_VAL.search(v) or _ICD_VAL.search(v)) / n
    feats["f:doc_r"] = sum(1 for v in clean if _DOC_VAL.match(v)) / n
    feats["f:at_r"] = sum(1 for v in clean if "@" in v) / n
    feats["f:comma_r"] = sum(1 for v in clean if "," in v) / n
    feats["f:digit_any_r"] = sum(1 for v in clean if any(c.isdigit() for c in v)) / n
    feats["f:digit_only_r"] = sum(1 for v in clean if v.isdigit()) / n
    feats["f:deva_r"] = sum(1 for v in clean if any("\u0900" <= c <= "\u097f" for c in v)) / n
    feats["f:title_2w_r"] = sum(
        1 for v in clean
        if 2 <= len(v.split()) <= 4
        and all(w[0].isupper() for w in v.split() if w and w[0].isalpha())
        and not any(c.isdigit() for c in v)
        and not _DOC_VAL.match(v)
    ) / n
    feats["f:deva_2w_r"] = sum(
        1 for v in clean
        if 2 <= len(v.split()) <= 4
        and any("\u0900" <= c <= "\u097f" for c in v)
        and not any(c.isdigit() for c in v)
        and not _DOC_VAL.match(v)
    ) / n
    feats["f:addr_kw_r"] = sum(
        1 for v in clean
        if any(w.casefold().strip(",.") in ADDR_CUES for w in v.split())
    ) / n
    feats["f:clin_kw_r"] = sum(
        1 for v in clean
        if any(w.casefold().strip(",.()") in CLINICAL_CUES for w in v.split())
    ) / n
    feats["f:avg_words"] = min(10.0, sum(len(v.split()) for v in clean) / n) / 10.0
    feats["f:avg_len"] = min(60.0, sum(len(v) for v in clean) / n) / 60.0
    feats["f:uniq_r"] = len(set(clean)) / n

    # Character 2-3 grams over sampled values (L2-normalized TF)
    ngram_counts: Counter[str] = Counter()
    for v in clean[:80]:
        s = " " + v.casefold()[:48] + " "
        for k in (2, 3):
            for idx in range(len(s) - k + 1):
                ngram_counts[f"g{k}:{s[idx:idx + k]}"] += 1
    norm = math.sqrt(sum(c * c for c in ngram_counts.values())) or 1.0
    for ng, cnt in ngram_counts.items():
        feats[ng] = cnt / norm
    return feats


class ColumnValueClassifier:
    """Pure-Python softmax multinomial logistic regression for unseen column headers."""

    def __init__(self, payload: dict[str, Any]):
        self.classes: list[str] = payload["classes"]
        self.intercept: list[float] = payload["intercept"]
        self.weights: dict[str, list[float]] = payload["weights"]

    @classmethod
    def load(cls, path: Path) -> "ColumnValueClassifier":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return cls(json.load(f))

    def predict_proba(self, values: list[str]) -> dict[str, float]:
        feats = extract_column_features(values)
        if not feats:
            return {c: 0.0 for c in self.classes}
        k = len(self.classes)
        logits = list(self.intercept)
        weights = self.weights
        for fname, fval in feats.items():
            w = weights.get(fname)
            if w is not None:
                for c in range(k):
                    logits[c] += w[c] * fval
        m = max(logits)
        exps = [math.exp(z - m) for z in logits]
        zsum = sum(exps) or 1.0
        return {self.classes[c]: exps[c] / zsum for c in range(k)}

    def classify_column(self, values: list[str], *, threshold: float = 0.90) -> str | None:
        clean = [v.strip() for v in values if v and v.strip()]
        if len(clean) < 2:
            return None
        probs = self.predict_proba(clean)
        best_cls = max(probs, key=lambda c: probs[c])
        if best_cls in ("CLINICAL", "OTHER"):
            return None
        if probs[best_cls] < threshold:
            return None
        # Repeated names are common in homonym rows. Requiring two distinct values
        # here silently skipped a high-confidence NAME column such as
        # Entity_Alpha=["Ananya Sharma", "Ananya Sharma"]. Keep that case, but
        # require a strong score and person-shaped values. Other classes still
        # need variation so repeated generic values are not over-interpreted.
        if len(set(clean)) < 2:
            if (
                best_cls != "NAME"
                or probs.get("NAME", 0.0) < max(threshold, 0.90)
                or not all(_person_name_shape(value) for value in clean)
            ):
                return None
        # Strict clinical protection: never touch a column with non-trivial clinical signal
        if probs.get("CLINICAL", 0.0) >= 0.05:
            return None
        # Extra doctor guard for NAME columns
        if best_cls == "NAME" and any(_DOC_VAL.match(v) for v in clean):
            return None
        return best_cls


_PERSON_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)


def _person_name_shape(value: str) -> bool:
    """Conservative shape gate for repeated, header-blind person-name values."""
    words = _PERSON_WORDS.findall(value.strip())
    return 2 <= len(words) <= 5 and all(len(word) >= 2 for word in words)


# --------------------------------------------------------------------------- Singleton lazy loader
class HybridModels:
    def __init__(self):
        self.ner: LinearChainCRF | None = None
        self.col_clf: ColumnValueClassifier | None = None
        self._loaded = False

    def load_from(self, models_dir: Path) -> None:
        if self._loaded:
            return
        ner_path = models_dir / "ner_crf.json.gz"
        col_path = models_dir / "col_clf.json.gz"
        if ner_path.is_file():
            self.ner = LinearChainCRF.load(ner_path)
        if col_path.is_file():
            self.col_clf = ColumnValueClassifier.load(col_path)
        self._loaded = True


MODELS = HybridModels()
