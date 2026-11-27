#!/usr/bin/env python3
"""Offline Secret Wards record sanitization and release reporting (v5 hybrid).

Usage: python main.py --input <file or directory> --output <empty output dir> [--policy <policy.yaml>]
Standard library only, Python 3.10+. Zero network calls, CPU-only, deterministic.
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
import hmac
import html
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import uuid
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

try:
    from ml_models import MODELS as HYBRID_MODELS
except ImportError:
    HYBRID_MODELS = None

# --------------------------------------------------------------------------- policy
DEFAULT_CATEGORIES = frozenset({
    "PHONE", "AADHAAR", "ABHA", "EMAIL", "PAN", "NAME", "MRN",
    "ENCOUNTER", "DOB", "ADDRESS", "RELATIVE", "INSURANCE_ID", "SOURCE_PATH",
})


def _parse_bool(val, default: bool = True) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    s = str(val).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_list(val) -> list[str]:
    if not val:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    return [item.strip() for item in str(val).split(",") if item.strip()]


def load_policy(path: Path) -> dict:
    """Tiny `key: value` reader for config/policy.yaml (no PyYAML needed)."""
    policy = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line:
                k, v = (x.strip() for x in line.split(":", 1))
                if v.lstrip("-").isdigit():
                    policy[k] = int(v)
                elif re.fullmatch(r"-?\d+\.\d+", v):
                    policy[k] = float(v)
                elif v.lower() in {"true", "false"}:
                    policy[k] = v.lower() == "true"
                else:
                    policy[k] = v
    return policy


HERE = Path(__file__).resolve().parent
POLICY: dict = load_policy(HERE / "config" / "policy.yaml")
SECRET = os.environ.get("RAKSHA_SECRET", "").encode()  # never print or write this

# Runtime policy state (populated by apply_policy)
ENABLED_CATEGORIES: frozenset[str] = DEFAULT_CATEGORIES
EXTRA_REDACT_FIELDS: frozenset[str] = frozenset()
EXTRA_PRESERVE_FIELDS: frozenset[str] = frozenset()
EXTRA_REDACT_TERMS: tuple[str, ...] = ()
EXTRA_REDACT_REGEX: re.Pattern | None = None
SHIFT_DATES_ENABLED: bool = True
GENERALIZE_AGES_ENABLED: bool = True
PRESERVE_DOCTORS_ENABLED: bool = True
HASH_FILENAMES_ENABLED: bool = True
ML_FALLBACK_ENABLED: bool = True
ML_NER_THRESHOLD: float = 0.85
ML_COL_THRESHOLD: float = 0.80


def apply_policy(policy: dict) -> None:
    global POLICY, ENABLED_CATEGORIES, EXTRA_REDACT_FIELDS, EXTRA_PRESERVE_FIELDS
    global EXTRA_REDACT_TERMS, EXTRA_REDACT_REGEX
    global SHIFT_DATES_ENABLED, GENERALIZE_AGES_ENABLED, PRESERVE_DOCTORS_ENABLED, HASH_FILENAMES_ENABLED
    global ML_FALLBACK_ENABLED, ML_NER_THRESHOLD, ML_COL_THRESHOLD

    POLICY = dict(policy)
    SHIFT_DATES_ENABLED = _parse_bool(POLICY.get("shift_dates", True), True)
    GENERALIZE_AGES_ENABLED = _parse_bool(POLICY.get("generalize_ages", True), True)
    PRESERVE_DOCTORS_ENABLED = _parse_bool(POLICY.get("preserve_doctors", True), True)
    HASH_FILENAMES_ENABLED = _parse_bool(POLICY.get("hash_sensitive_filenames", True), True)
    ML_FALLBACK_ENABLED = _parse_bool(POLICY.get("ml_fallback", True), True)
    try:
        ML_NER_THRESHOLD = max(0.50, min(0.99, float(POLICY.get("ml_ner_threshold", 0.85))))
    except (TypeError, ValueError):
        ML_NER_THRESHOLD = 0.85
    try:
        ML_COL_THRESHOLD = max(0.50, min(0.99, float(POLICY.get("ml_col_threshold", 0.80))))
    except (TypeError, ValueError):
        ML_COL_THRESHOLD = 0.80

    cats = _parse_list(POLICY.get("redact_categories"))
    ENABLED_CATEGORIES = frozenset(c.upper() for c in cats) if cats else DEFAULT_CATEGORIES

    EXTRA_REDACT_FIELDS = frozenset(field_label(f) for f in _parse_list(POLICY.get("extra_redact_fields")))
    EXTRA_PRESERVE_FIELDS = frozenset(field_label(f) for f in _parse_list(POLICY.get("extra_preserve_fields")))
    EXTRA_REDACT_TERMS = tuple(
        sorted(_parse_list(POLICY.get("extra_redact_terms")), key=lambda s: (-len(s), s))
    )
    raw_rx = str(POLICY.get("extra_redact_regex") or "").strip()
    if raw_rx:
        try:
            EXTRA_REDACT_REGEX = re.compile(raw_rx)
        except re.error:
            EXTRA_REDACT_REGEX = None
    else:
        EXTRA_REDACT_REGEX = None

    # Clear caches that depend on policy
    field_kind.cache_clear()
    dynamic_field_kind.cache_clear()
    date_shift_days.cache_clear()


def _category_enabled(kind: str | None) -> bool:
    if not kind:
        return False
    if kind == "CUSTOM":
        return True
    if kind == "NATIONAL_ID":
        return "AADHAAR" in ENABLED_CATEGORIES or "ABHA" in ENABLED_CATEGORIES or "NATIONAL_ID" in ENABLED_CATEGORIES
    if kind == "AADHAAR_MASKED":
        return "AADHAAR" in ENABLED_CATEGORIES
    return kind in ENABLED_CATEGORIES


# --------------------------------------------------------------------------- Indic digit & script helpers
_INDIC_DIGIT_TRANS = str.maketrans("०१२३४५६७८९", "0123456789")


def ascii_digits(text: str) -> str:
    return text.translate(_INDIC_DIGIT_TRANS)


_DEVA_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh",
    "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}
_DEVA_VOWELS = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऋ": "ri",
}
_DEVA_MATRAS = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ृ": "ri",
    "ं": "n", "ँ": "n", "ः": "h",
}
_NAME_HONORIFICS = {"mr", "mrs", "ms", "shri", "smt", "kumari", "km", "md", "mohd", "mohammed", "muhammad"}


def _deva_to_latin(text: str) -> str:
    """Lightweight Devanagari -> approximate Latin transliteration for cross-script linkage."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # Handle nukta combined character
        if i + 1 < n and text[i + 1] == "\u093c" and (ch + "\u093c") in _DEVA_CONSONANTS:
            pair = ch + "\u093c"
            nxt = text[i + 2] if i + 2 < n else ""
            out.append(_DEVA_CONSONANTS[pair])
            if nxt == "्":
                i += 3
            elif nxt in _DEVA_MATRAS:
                out.append(_DEVA_MATRAS[nxt])
                i += 3
            else:
                if nxt and nxt in _DEVA_CONSONANTS:
                    out.append("a")
                i += 2
            continue
        if ch in _DEVA_CONSONANTS:
            nxt = text[i + 1] if i + 1 < n else ""
            out.append(_DEVA_CONSONANTS[ch])
            if nxt == "्":
                i += 2
            elif nxt in _DEVA_MATRAS:
                out.append(_DEVA_MATRAS[nxt])
                i += 2
            else:
                # Inherent schwa inside words (drop word-final schwa)
                if nxt and (nxt in _DEVA_CONSONANTS or nxt in _DEVA_MATRAS):
                    out.append("a")
                i += 1
        elif ch in _DEVA_VOWELS:
            out.append(_DEVA_VOWELS[ch])
            i += 1
        elif ch in _DEVA_MATRAS:
            out.append(_DEVA_MATRAS[ch])
            i += 1
        elif ch == "्" or ch == "\u093c":
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


@lru_cache(maxsize=4096)
def canonical_person_name(name: str) -> str:
    """Normalize English/Hinglish/Devanagari names into a canonical ASCII phonetic form for linkage."""
    normed = unicodedata.normalize("NFKC", name).casefold()
    if any("\u0900" <= c <= "\u097f" for c in normed):
        normed = _deva_to_latin(normed)
    # Strip diacritics & punctuation
    normed = "".join(c for c in unicodedata.normalize("NFKD", normed) if not unicodedata.combining(c))
    tokens = re.findall(r"[a-z]+", normed)
    cleaned = []
    for t in tokens:
        if t in {"md", "mohd", "mohammad", "mohammed", "muhammad", "muhammed"}:
            cleaned.append("mohammad")
        elif t in {"mr", "mrs", "ms", "shri", "smt", "kumari", "km", "master", "baby"}:
            continue
        else:
            # Collapse common vowel/double-letter spelling variations (ee->i, oo->u, aa->a, w->v, ph->f)
            s = t.replace("ph", "f").replace("w", "v").replace("ee", "i").replace("oo", "u").replace("aa", "a")
            s = re.sub(r"(.)\1+", r"\1", s)
            # Common English spellings and Devanagari transliteration of
            # अय्यर are equivalent in this surname (Iyer/Ayyar/Ayar).
            if s in {"iyar", "ayar", "aiyar"}:
                s = "iyer"
            cleaned.append(s)
    return " ".join(cleaned)


# --------------------------------------------------------------------------- pseudonyms & dates
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U


@lru_cache(maxsize=4096)
def pseudonym(patient_key: str) -> str:
    """Stable, non-reversible ID: HMAC-SHA256 keyed with RAKSHA_SECRET (never a plain hash)."""
    digest = hmac.new(SECRET, patient_key.encode("utf-8"), hashlib.sha256).digest()
    n = int.from_bytes(digest[:8], "big")
    code = "".join(_ALPHABET[(n >> (5 * i)) & 31] for i in range(12))
    return f"PSN-{code}"


@lru_cache(maxsize=4096)
def date_shift_days(patient_key: str) -> int:
    """Per-patient shift in [-max, +max], never 0. Preserves stay lengths and intervals."""
    m = max(1, int(POLICY.get("date_shift_max_days", 180)))
    d = hmac.new(SECRET, b"shift|" + patient_key.encode("utf-8"), hashlib.sha256).digest()
    v = int.from_bytes(d[:4], "big") % (2 * m) - m
    return v if v != 0 else 1


def shift_date(value: dt.date, patient_key: str) -> dt.date:
    if not SHIFT_DATES_ENABLED:
        return value
    return value + dt.timedelta(days=date_shift_days(patient_key))


def age_band(age: int, width=None) -> str:
    """Return an inclusive interval containing this age."""
    if not GENERALIZE_AGES_ENABLED:
        return str(age)
    w = max(1, int(width or POLICY.get("age_band_years", 5)))
    lo = (age // w) * w
    return f"{lo}-{lo + w - 1}"


def private_label(value: str) -> str:
    digest = hmac.digest(SECRET, b"label|" + value.encode("utf-8"), "sha256")
    return "item-" + digest[:12].hex()


# --------------------------------------------------------------------------- detection
_D = r"[0-9\u0966-\u096f]"
_D69 = r"[6-9\u096c-\u096f]"
_PHONE_SEP = r"[\s().-]*"
PHONE_PATTERN = re.compile(
    rf"(?<!{_D})(?:(?:\+|00)?(?:91|९१){_PHONE_SEP})?"
    rf"0?{_D69}{_D}{{4}}(?:{_PHONE_SEP}{_D}){{5}}(?!{_D})"
)
PATTERNS = [
    ("ABHA", re.compile(rf"(?<!{_D}){_D}{{2}}[- ]?{_D}{{4}}[- ]?{_D}{{4}}[- ]?{_D}{{4}}(?!{_D})")),
    ("AADHAAR_MASKED", re.compile(rf"(?i)(?<![A-Za-z0-9])(?:x{{4}}|[*X]{{4}})[\s-]?(?:x{{4}}|[*X]{{4}})[\s-]?{_D}{{4}}(?!{_D})")),
    ("PHONE", PHONE_PATTERN),
    ("AADHAAR", re.compile(rf"(?<!{_D})(?<![0-9a-fA-F]{{4}}-){_D}{{4}}[\s-]?{_D}{{4}}[\s-]?{_D}{{4}}(?!{_D})")),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
]
ID_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2,8}[-/]?(?:\d{2,4}[-/])?\d{5,12}(?![A-Za-z0-9])")
PRIVATE_MAPS = {"byname", "byuhid", "bymrn", "bypatientid"}
ATTACHMENT_FIELDS = {"data", "content", "payload"}
PERSON_WORD = r"[A-ZÀ-ÖØ-Þ][^\W\d_]*(?:[.'’-][^\W\d_]+)*"
PERSON_NAME = rf"{PERSON_WORD}(?:[ \t]+{PERSON_WORD}){{1,4}}"
PERSON_FRAGMENT = rf"{PERSON_WORD}(?:[ \t]+{PERSON_WORD}){{0,4}}"
_TEXT_PERSON_WORD = rf"(?:{PERSON_WORD}|[\u0900-\u097f]+)"
_TEXT_PERSON_NAME = rf"{_TEXT_PERSON_WORD}(?:[ \t]+{_TEXT_PERSON_WORD}){{1,3}}"
TEXT_NOTE_SUBJECT = re.compile(
    rf"(?i)\b(?:discharge|follow[ -]?up|patient|clinical)?[ \t]*(?:note|summary|report)"
    rf"[ \t]+(?:for|of)[ \t]+(?P<name>{_TEXT_PERSON_NAME})(?=$|[,.\r\n])"
)
TEXT_LEADING_CONTACT = re.compile(
    rf"(?im)^[ \t]*(?P<name>{_TEXT_PERSON_NAME})"
    rf"(?:[ \t]*\((?P<alias>{_TEXT_PERSON_NAME})\))?[ \t]*,?[ \t]*"
    rf"(?:mobile|phone)\b"
)
FRAGMENTED_RELATION = re.compile(
    rf"(?i)(?<![\w])(?P<patient>{PERSON_FRAGMENT})[ \t]*,[ \t]*"
    rf"(?P<relation>[sdw]/o)[ \t]+(?P<relative>{PERSON_FRAGMENT})"
    rf"(?=$|[,;.\r\n])"
)
CARE_OF_PERSON = re.compile(
    rf"(?i)(?P<prefix>\b(?:c\s*/\s*o|care[ \t]+of)[ \t]+)"
    rf"(?P<name>{PERSON_NAME}|{PERSON_WORD})"
    rf"(?=$|\r?\n|[,;.!?]|[ \t]+(?:for|with|has|had|is|was|ne|ko|se|aur|tha|hai|reported|came|stable)\b)"
)
CARE_OF_CLINICAL_WORDS = frozenset({
    "fever", "cough", "pain", "headache", "vomiting", "diarrhea", "diarrhoea",
    "breathlessness", "disease", "syndrome", "hypertension", "diabetes", "asthma",
    "infection", "rash", "weakness", "parkinson's disease", "parkinson disease",
})
KNOWN_CASE_OF_PREFIX = re.compile(r"(?i)\bK[ \t]*/[ \t]*$")
CONTACT_NAME = re.compile(
    rf"(?P<prefix>(?i:\b(?:called|witnessed|reported) by)[ \t]+)(?!Dr\.? )"
    rf"(?P<name>{PERSON_NAME})(?=[ ,;.!]?(?:[ \t]+\+?\d|[ ,;.!]*$)|[ \t]*[,;])",
    re.MULTILINE,
)
VISITOR_NAME = re.compile(rf"(?m)^(?P<prefix>\d{{1,2}}:\d{{2}}[ \t]+-[ \t]+){PERSON_NAME}(?=[ \t]*\((?:attendant|visitor|relative)\b)")
RELATIVE_NAME = re.compile(
    rf"(?i)(?P<prefix>\b[sdw]/o[ \t]*[:：]?[ \t]*)"
    rf"(?P<name>{_TEXT_PERSON_WORD}(?:[ \t]+{_TEXT_PERSON_WORD}){{0,3}})"
    rf"(?=$|[,;)|\r\n.!?]|[ \t]+(?:BP|Hb|SpO2|Temp(?:erature)?|Pulse|Diagnosis|C/O|K/C/O|Rx|admitted|discharged)\b)"
)
CHAT_SENDER = re.compile(
    r"(?im)^(?P<prefix>\[\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4},[ \t]+\d{1,2}:\d{2}[^\]\r\n]*\][ \t]+)"
    r"(?!Dr\.?[ \t])[^:\r\n]+(?=:[ \t])"
)
HONORIFIC_NAME = re.compile(
    rf"(?P<prefix>(?<![\w])(?<!Dr\. )(?<!Dr )(?<!dr\. )(?<!dr ))"
    rf"{PERSON_WORD}(?:[ \t]+{PERSON_WORD}){{0,3}}[ \t]+(?i:ji|sahab|didi|bhai|bhaiya|behenji|chachu|babu|amma)\b"
)
RELATIVE_CLAUSE = re.compile(
    rf"(?m)^(?P<prefix>[ \t]*){PERSON_WORD}(?:[ \t]+{PERSON_WORD}){{0,4}}(?=,[ \t]*(?i:[sdw]/o)\b)"
)
POSSESSIVE_NAME = re.compile(rf"(?P<prefix>(?<!\w)(?<!Dr\. )){PERSON_WORD}(?=['’]s[ \t]+(?i:attendant|relative|family|guardian)\b)")
VITAL_SUBJECT = re.compile(
    rf"(?P<prefix>(?<!\w)(?<!Dr\. )){PERSON_WORD}(?:[ \t]+{PERSON_WORD}){{0,2}}"
    r"(?=[ \t]+(?i:ka|ki|ke)[ \t]+(?i:BP|pulse|sugar|temperature)\b)"
)
TIMED_PATIENT = re.compile(
    rf"(?m)^(?P<prefix>\d{{1,2}}:\d{{2}}[ \t]+[-–][ \t]+)(?!(?i:dr\.?|doctor)\b)"
    rf"{PERSON_NAME}(?=[ \t]+[-–][ \t]+(?i:k/c/o|h/o|c/o)\b)"
)
CONTEXT_PATTERNS = (CONTACT_NAME, VISITOR_NAME, CHAT_SENDER, HONORIFIC_NAME,
                    RELATIVE_CLAUSE, POSSESSIVE_NAME, VITAL_SUBJECT, TIMED_PATIENT)

FIELD_LABELS = {
    "NAME": "patient name|patient's name|patient full name|full patient name|name of patient|patient legal name|first name|last name|given name|family name|surname|patient|naam|naame|naem|नाम|मरीज़ का नाम|मरीज का नाम|रोगी का नाम|client name|subject name|beneficiary name",
    "RELATIVE": "relative name|guardian|guardian name|attendant|attendant name|next of kin|nok|care of|father name|mother name|spouse name|husband name|pita/pati ka naam|पिता का नाम|पति का नाम|अभिभावक",
    "MRN": "patient id|patient ref|mrn|uhid|uhid no|hospital uhid|registration no|reg no|chart id|chart number|medical record number|medical record id|record identifier|local id|hospital number|registration number|patient identifier|hospital id|case no|case id|file no|पंजीकरण सं.|पंजीकरण संख्या|पंजीकरण नंबर|पंजीयन संख्या",
    "ENCOUNTER": "record id|record no|ipd no|opd no|ip no|op no|admission id|encounter id|visit id|आईपीडी सं.",
    "PHONE": "phone|phone no|phone number|telephone|tel|contact|contact no|contact number|callback|mobile|mobile number|mobile no|mob|cell|whatsapp|मोबाइल|मोबाइल नं.|फ़ोन|फोन",
    "EMAIL": "email|email address|e-mail|mail|abha address",
    "NATIONAL_ID": "aadhaar|aadhar|aadhaar no|aadhar no|abha|abha no|abha id|health id|national id|gov id|govt id|आधार|आभा",
    "INSURANCE_ID": "pmjay id|insurance id|policy no|policy number|payer pan|member id|subscriber id",
    "DOB": "dob|dob (mm/dd/yyyy)|dob (dd/mm/yyyy)|date of birth|date of birht|birth date|janm tithi|जन्म तिथि",
    "ADDRESS": "street|street address|home address|residential address|permanent address|current address|pata|pincode|pin code|postal code|pin|village|gaon|village/mohalla|gram/mohalla|address|address note|address (attendant)|पता|ग्राम|zip|zip code|tehsil|tahsil|residence block|landmark|mohalla|locality|house number|तहसील",
    "SOURCE_PATH": "source path|original filename|original file path",
}
ROLE_PREFIXES = (
    "patient", "beneficiary", "registrant", "primary", "home", "emergency",
    "current", "attending", "subject", "member", "insured", "client", "ward",
)


@lru_cache(maxsize=1024)
def field_label(label: str) -> str:
    # Remove separators without stripping Devanagari combining marks.
    return re.sub(r"[\s_.()/’'\-\u200b-\u200d\ufeff]+", "", unicodedata.normalize("NFKC", label).casefold())


FIELD_KIND = {
    field_label(label): kind
    for kind, labels in FIELD_LABELS.items()
    for label in labels.split("|")
}


@lru_cache(maxsize=2048)
def field_kind(label):
    if label in EXTRA_PRESERVE_FIELDS:
        return None
    if label in EXTRA_REDACT_FIELDS:
        return "CUSTOM"
    if label in FIELD_KIND:
        return FIELD_KIND[label]
    # Vendors qualify demographic labels with a role or a position in the form.
    for prefix in ROLE_PREFIXES:
        if label.startswith(prefix):
            tail = label[len(prefix):]
            if tail in {"fullname", "name", "displayname", "legalname"}:
                return "NAME"
            if tail in {"recordnumber", "chart", "recordid", "identifier", "number", "ref", "id"}:
                return "MRN"
            return FIELD_KIND.get(tail)
    return None


# --------------------------------------------------------------------------- Dynamic cross-script label resolver
_LABEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|[\s_./()’'\"\-:,;|+]+")
_CONNECTOR_TOKS = frozenset({
    "ka", "ki", "ke", "ko", "se", "me", "mein", "par", "of", "the", "for", "to", "in", "by",
    "no", "num", "number", "nambar", "nanbar", "sankhya", "sn", "detail", "details", "info", "kiya", "hai",
})
_CLINICIAN_GUARD_TOKS = frozenset({
    "dr", "doctor", "doktar", "daktar", "daktor", "consultant", "kansaltent", "physician",
    "fisiyan", "chikitsak", "vaidya", "surgeon", "sarjan", "nurse", "nars", "sister",
    "sistar", "asha", "anm", "practitioner", "clinician", "prescriber", "refered", "referred",
    "revieved", "reviewed", "specialist", "prof", "profasar",
})
_CLINICAL_GUARD_TOKS = frozenset({
    "medicine", "medisin", "medication", "drug", "drag", "dava", "davai", "goli", "tablet",
    "teblet", "capsule", "kapsul", "injection", "injekshan", "syrup", "sirap", "dose", "dosage",
    "rx", "diagnosis", "daignosis", "disease", "bimari", "rog", "symptom", "laksan", "lakshan",
    "complaint", "shikayat", "sikayat", "test", "lab", "leb", "pathology", "parameter", "analyte",
    "ward", "vard", "department", "vibhag", "unit", "bed", "room", "kamra", "pharmacy",
    "report", "riport", "bill", "bil", "claim", "klem", "invoice", "receipt", "amount", "rashi",
    "fee", "shulk", "blood", "rakt", "group", "protocol", "trial", "study", "arm", "note", "notes",
    "summary", "vitals", "plan", "advice", "history", "investigation", "procedure", "surgery",
    "allergies", "allergy", "impression", "finding", "reference", "prescribed",
})
_FACILITY_GUARD_TOKS = frozenset({
    "hospital", "aspatal", "haspatal", "clinic", "klinik", "facility", "center", "centre", "kendra",
})
_PATIENT_SUBJ_TOKS = frozenset({
    "patient", "peshent", "pesent", "peshant", "rogi", "marij", "mariz", "beneficiary", "registrant",
    "subject", "client", "member", "insured", "vyakti", "person", "admi", "mahila", "purush", "baccha", "self", "khud",
})
_RELATIVE_SUBJ_TOKS = frozenset({
    "relative", "riletiv", "guardian", "gardiyan", "gardian", "attendant", "atendent", "nok", "kin",
    "father", "fadar", "pita", "mother", "madar", "mata", "husband", "hasbend", "hasbaind", "pati",
    "wife", "vaif", "patni", "spouse", "spaus", "son", "putra", "beta", "daughter", "putri", "beti",
    "brother", "bhai", "parijan", "parivar", "abhivavak", "abhibhavak", "timardar", "rishtedar", "ristedar", "careof",
})
_NAME_CONCEPT_TOKS = frozenset({
    "name", "nam", "nem", "fullname", "firstname", "lastname", "surname", "sarnem",
    "givenname", "familyname", "legalname", "displayname", "puranam", "subhnam", "shubhnam",
})
_NAME_QUAL_TOKS = frozenset({
    "full", "ful", "first", "fast", "last", "given", "family", "legal", "pura", "poora", "shubh", "subh", "asli", "real",
})
_PHONE_CONCEPT_TOKS = frozenset({
    "phone", "fone", "fon", "mobile", "mobail", "mob", "cell", "sel", "tel", "telephone",
    "telifon", "contact", "kontekt", "kontakt", "callback", "kolbek", "vhatsapp", "whatsapp",
    "sampark", "durbhash", "durbash",
})
_EMAIL_CONCEPT_TOKS = frozenset({"email", "imel", "mail", "mel", "gmail", "jimel"})
_NATIONAL_ID_TOKS = frozenset({"adhar", "aadhar", "abha", "uidai", "nationalid", "govtid", "healthid"})
_INSURANCE_TOKS = frozenset({"pmjay", "insurance", "insorens", "bima", "policy", "polisi", "subscriber"})
_DOB_EXACT_TOKS = frozenset({"dob", "birthdate", "janmtithi", "janamtithi", "janmdin"})
_BIRTH_WORD_TOKS = frozenset({"birth", "barth", "janm", "janam", "paidaish", "pedais"})
_DATE_WORD_TOKS = frozenset({"date", "det", "tithi", "tarikh", "tarik", "dinank"})
_ADDRESS_CONCEPT_TOKS = frozenset({
    "address", "adres", "edres", "pata", "street", "strit", "house", "haus", "makan", "ghar",
    "niwas", "nivas", "niwasi", "nivasi", "village", "vilej", "gaon", "ganv", "gram", "mohalla",
    "mohala", "colony", "koloni", "gali", "road", "rod", "marg", "lane", "len", "locality",
    "lokeliti", "landmark", "lendmark", "tehsil", "tahsil", "pincode", "pinkod", "pin",
    "postal", "zip", "thana", "basti", "residence", "residential", "permanent", "domicile",
})
_MRN_STRONG_TOKS = frozenset({"mrn", "uhid", "chart", "panjikaran", "panjiyan", "pnjikaran", "pnjiyan", "patientid", "regno"})
_MRN_WEAK_TOKS = frozenset({"id", "aidi", "reg", "registration", "rejistresan", "record", "rikord", "case", "file", "identifier"})
_ENCOUNTER_TOKS = frozenset({"encounter", "admissionid", "visitid", "ipdno", "opdno"})
_AGE_CONCEPT_TOKS = frozenset({"age", "ej", "umar", "umr", "ayu", "vay", "agesex", "ageyrs", "ageyears"})
_DISTRICT_CONCEPT_TOKS = frozenset({"district", "distrikt", "dist", "jila", "janpad"})

_FUZZY_BUCKETS = (
    _CLINICIAN_GUARD_TOKS, _CLINICAL_GUARD_TOKS, _FACILITY_GUARD_TOKS,
    _PATIENT_SUBJ_TOKS, _RELATIVE_SUBJ_TOKS, _NAME_CONCEPT_TOKS,
    _PHONE_CONCEPT_TOKS, _EMAIL_CONCEPT_TOKS, _NATIONAL_ID_TOKS,
    _ADDRESS_CONCEPT_TOKS, _BIRTH_WORD_TOKS, _DATE_WORD_TOKS,
    _AGE_CONCEPT_TOKS, _DISTRICT_CONCEPT_TOKS,
)


def _edit1(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = j = diff = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            diff += 1
            if diff > 1:
                return False
            j += 1
    return True


def _phonetic_label_token(tok: str) -> str:
    s = unicodedata.normalize("NFKC", tok).casefold()
    if any("\u0900" <= c <= "\u097f" for c in s):
        s = _deva_to_latin(s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]", "", s)
    if not s:
        return ""
    s = s.replace("ph", "f").replace("w", "v").replace("z", "j").replace("q", "k")
    s = s.replace("ee", "i").replace("oo", "u").replace("aa", "a")
    s = re.sub(r"(.)\1+", r"\1", s)
    return s


def _in_bucket(toks: set[str], bucket: frozenset[str], *, allow_fuzzy: bool = True) -> bool:
    if toks & bucket:
        return True
    if not allow_fuzzy:
        return False
    for t in toks:
        if len(t) >= 5:
            for cand in bucket:
                if len(cand) >= 5 and _edit1(t, cand):
                    return True
    return False


@lru_cache(maxsize=4096)
def _label_token_set(raw_label: str) -> tuple[frozenset[str], bool]:
    """Return (phonetic non-connector tokens, had_devanagari) for any English/Hindi/Hinglish label."""
    norm = unicodedata.normalize("NFKC", raw_label)
    has_deva = any("\u0900" <= c <= "\u097f" for c in norm)
    parts = [p for p in _LABEL_SPLIT_RE.split(norm) if p]
    toks = set()
    for p in parts:
        pt = _phonetic_label_token(p)
        if pt and pt not in _CONNECTOR_TOKS:
            toks.add(pt)
    return frozenset(toks), has_deva


@lru_cache(maxsize=4096)
def dynamic_field_kind(raw_label: str) -> str | None:
    """Word-order-independent cross-script (English / Hindi-in-English / English-in-Hindi) label classifier."""
    compact = field_label(raw_label)
    if not compact or compact in EXTRA_PRESERVE_FIELDS:
        return None
    if compact in EXTRA_REDACT_FIELDS:
        return "CUSTOM"
    if len(raw_label) > 64:
        return None
    toks, has_deva = _label_token_set(raw_label)
    if not toks or len(toks) > 6:
        return None

    # 1. Strict clinician & clinical guardrails: NEVER redact doctor / drug / disease / bill labels
    if _in_bucket(toks, _CLINICIAN_GUARD_TOKS):
        return None
    if _in_bucket(toks, _CLINICAL_GUARD_TOKS):
        return None
    has_facility = _in_bucket(toks, _FACILITY_GUARD_TOKS)

    # 2. Strong non-ambiguous PII concepts (any word order, any script)
    if _in_bucket(toks, _EMAIL_CONCEPT_TOKS):
        return None if has_facility else "EMAIL"
    if _in_bucket(toks, _PHONE_CONCEPT_TOKS):
        return None if has_facility else "PHONE"
    if _in_bucket(toks, _NATIONAL_ID_TOKS, allow_fuzzy=False):
        return "NATIONAL_ID"
    if _in_bucket(toks, _INSURANCE_TOKS):
        return "INSURANCE_ID"
    if _in_bucket(toks, _DOB_EXACT_TOKS, allow_fuzzy=False) or (
        _in_bucket(toks, _BIRTH_WORD_TOKS) and (_in_bucket(toks, _DATE_WORD_TOKS) or _in_bucket(toks, _PATIENT_SUBJ_TOKS) or len(toks) <= 2)
    ):
        return "DOB"
    if _in_bucket(toks, _MRN_STRONG_TOKS, allow_fuzzy=False):
        return "MRN"
    if _in_bucket(toks, _ENCOUNTER_TOKS, allow_fuzzy=False):
        return "ENCOUNTER"
    if (has_facility or _in_bucket(toks, _PATIENT_SUBJ_TOKS)) and _in_bucket(toks, _MRN_WEAK_TOKS, allow_fuzzy=False):
        if not _in_bucket(toks, _NAME_CONCEPT_TOKS, allow_fuzzy=False) and not _in_bucket(toks, _ADDRESS_CONCEPT_TOKS):
            return "MRN"
    if has_facility:
        return None

    # 3. Relative vs Patient Name vs Address (word-order independent!)
    if _in_bucket(toks, _RELATIVE_SUBJ_TOKS):
        if _in_bucket(toks, _ADDRESS_CONCEPT_TOKS):
            return "ADDRESS"
        return "RELATIVE"
    if _in_bucket(toks, _ADDRESS_CONCEPT_TOKS):
        return "ADDRESS"
    if _in_bucket(toks, _NAME_CONCEPT_TOKS, allow_fuzzy=False):
        # Preserve bare single-word English "name" for clinical catalogs (e.g. drug_formulary.csv),
        # while catching Hindi/Hinglish/English-in-Hindi ("naam", "नाम", "नेम") or any qualified/patient name!
        if toks == {"name"} and not has_deva:
            return None
        if (
            _in_bucket(toks, _PATIENT_SUBJ_TOKS)
            or _in_bucket(toks, _NAME_QUAL_TOKS, allow_fuzzy=False)
            or bool(toks & {"nam", "nem"})
            or has_deva
        ):
            return "NAME"
    return None


def resolve_field_kind(raw_label: str) -> str | None:
    """Resolve field kind via exact/prefix schema table first, then dynamic cross-script resolver."""
    compact = field_label(raw_label)
    if compact in EXTRA_PRESERVE_FIELDS:
        return None
    if compact in EXTRA_REDACT_FIELDS:
        return "CUSTOM"
    return field_kind(compact) or dynamic_field_kind(raw_label)


@lru_cache(maxsize=2048)
def dynamic_is_age_label(raw_label: str) -> bool:
    if is_age_label(field_label(raw_label)):
        return True
    toks, _ = _label_token_set(raw_label)
    if not toks or len(toks) > 4 or _in_bucket(toks, _CLINICAL_GUARD_TOKS):
        return False
    return bool(toks & _AGE_CONCEPT_TOKS)


@lru_cache(maxsize=2048)
def dynamic_is_district_label(raw_label: str) -> bool:
    if is_district_label(field_label(raw_label)):
        return True
    toks, _ = _label_token_set(raw_label)
    if not toks or len(toks) > 4 or _in_bucket(toks, _CLINICAL_GUARD_TOKS):
        return False
    return _in_bucket(toks, _DISTRICT_CONCEPT_TOKS)


WORDS = re.compile(r"(?:[^\W_]|[\u0900-\u0963])+")
PROVIDER_PREFIX = re.compile(r"(?i)(?:\bdr\.?|\bdoctor|\bconsultant(?:\s+name)?|\bphysician|डॉ\.?)\s*[:=-]?\s*$")


class ReleaseVocabulary:
    """Index full names observed in explicit identity fields for this input only."""

    def __init__(self):
        self.trie = {}
        self.chart_ids = set()
        self.given_names = set()
        self.name_tokens = set()
        self.relative_names = set()

    def add_relative(self, name):
        if not isinstance(name, str) or not name.strip() or re.fullmatch(r"\[[A-Z_]+\]", name.strip()):
            return
        words = [m[0].casefold() for m in WORDS.finditer(name)]
        if 1 <= len(words) <= 6 and len(name) <= 96 and not any(c.isdigit() for c in name):
            self.relative_names.add(" ".join(words))

    def add(self, name):
        words = [m[0].casefold() for m in WORDS.finditer(name)]
        if not 2 <= len(words) <= 6 or len(name) > 96 or any(c.isdigit() for c in name):
            return
        self.given_names.add(words[0])
        self.name_tokens.update(words)
        for sequence in (words, list(reversed(words))):
            node = self.trie
            for word in sequence:
                node = node.setdefault(word, {})
            node[None] = True

    def redact(self, text):
        if not self.trie or not _category_enabled("NAME"):
            return text
        # Look ahead only after a token found in the vocabulary.
        pieces, end = [], 0
        for first in WORDS.finditer(text):
            if first.start() < end:
                continue
            node = self.trie.get(first[0].casefold())
            if node is None:
                continue
            at, longest = first.end(), None
            while node:
                sep = NAME_SEPARATOR.match(text, at)
                word = WORDS.match(text, sep.end()) if sep else None
                if not word:
                    break
                node = node.get(word[0].casefold())
                at = word.end()
                if node and None in node:
                    longest = at
            if longest and not (
                PRESERVE_DOCTORS_ENABLED and PROVIDER_PREFIX.search(text[max(0, first.start() - 40):first.start()])
            ):
                pieces.extend((text[end:first.start()], "[NAME]"))
                Stats.record_entity("NAME")
                end = longest
        return "".join([*pieces, text[end:]]) if pieces else text


NAME_SEPARATOR = re.compile(r"[ .,'’_\-\t]+")
VOCAB = ReleaseVocabulary()
NOTE_LABELS = [label for labels in FIELD_LABELS.values() for label in labels.split("|")] + [
    "name", "full name", "display name", "legal name", "record number", "chart", "record id", "identifier",
]
NOTE_ROLE = r"(?:(?:" + "|".join(ROLE_PREFIXES) + r")[ _\t-]+)?"
NOTE_FIELD = re.compile(
    r"(?im)(?:^|[ \t]{2,}|(?<=[;,|]))[ \t]*"
    r"(?P<label>" + NOTE_ROLE + r"(?:" + "|".join(re.escape(label).replace(r"\ ", r"[ _\t-]*") for label in NOTE_LABELS)
    + r"))[ \t]*[:：=][ \t]*(?P<value>[^\r\n;|]+?)(?=$|[\r;|]|(?:,|[ \t]{2,})[ \t]*[^:：=\r\n,;|]{1,30}[:：=]"
    r"|[ \t]+(?:(?:(?:" + "|".join(ROLE_PREFIXES) + r")[ \t]+)?age(?:[ \t]*(?:/sex|\([^)\r\n]{1,12}\)))?|dose|dosage|rx|diagnosis|BP|वय|आयु|उम्र)[ \t]*[:：=])"
)
# Dynamic generic label:value matcher for arbitrary word-order / Hinglish / English-in-Hindi note labels
DYNAMIC_NOTE_FIELD = re.compile(
    r"(?im)(?:^|[ \t]{2,}|(?<=[;,|]))[ \t]*"
    r"(?P<label>[^\r\n:：=;|\[\]]{2,48}?)[ \t]*[:：=][ \t]*"
    r"(?P<value>[^\r\n;|]+?)(?=$|[\r;|]|(?:,|[ \t]{2,})[ \t]*[^:：=\r\n,;|]{2,36}[:：=])"
)
PATIENT_FIELDS = {"name": "NAME", "fullname": "NAME", "id": "MRN"}
NESTED_FIELDS = {
    "patient": PATIENT_FIELDS,
    "patients": PATIENT_FIELDS,
    "demographics": PATIENT_FIELDS,
    "guardian": {"name": "RELATIVE"},
    "raisedby": {"name": "NAME"},
    "caller": {"name": "NAME"},
    "witness": {"name": "NAME"},
    "address": {"line": "ADDRESS", "house": "ADDRESS", "locality": "ADDRESS"},
}


class Stats:
    identifiers = 0
    generalized = 0
    suppressed = 0
    entities: Counter = Counter()

    @classmethod
    def reset(cls):
        cls.identifiers = 0
        cls.generalized = 0
        cls.suppressed = 0
        cls.entities = Counter()

    @classmethod
    def record_entity(cls, kind: str, count: int = 1):
        if count > 0:
            cls.identifiers += count
            cls.entities[kind] += count


DATE_TOKEN = re.compile(rf"(?<!{_D})(?:{_D}{{4}}([-./]){_D}{{1,2}}\1{_D}{{1,2}}|{_D}{{1,2}}([-./]){_D}{{1,2}}\2{_D}{{4}})(?!{_D})")
AGE_ROOTS = {"age", "agesex", "umar", "आयु", "उम्र", "वय", "ageyears", "ageyrs", "ageinyears", "ageatadmission", "ageatvisit"}
DISTRICT_ROOTS = {"district", "districtname", "dist", "jila", "जिला", "ज़िला", "जनपद"}
DATE_LABELS = {
    "date", "admissiondate", "admitdate", "dischargedate", "dateofadmission", "dateofdischarge",
    "visitdate", "registered", "registeredon", "regdate", "registrationdate", "collected",
    "collectedon", "reportedon", "effectivedatetime", "recordeddate",
    "performeddatetime", "authoredon", "start", "end", "birthdate", "admittedon", "dischargedon",
    "admittedat", "dischargedat", "admissiondatetime", "dischargedatetime",
    "checkindate", "checkoutdate", "enrolledon", "dateofservice", "servicedate", "dos", "admitdatte",
    "followupdate", "sampledate", "reportdate", "testdate", "admitted", "discharged",
}
DATE_EVENTS = ("admit", "admission", "discharge", "visit", "reg", "registration", "collected", "reported", "checkin", "checkout", "service", "followup", "sample", "test")
AGE_VALUE = re.compile(
    rf"^\s*({_D}{{1,3}})(?:\s*(?:y|yrs?|years?|वर्ष|साल))?(?:\s*/\s*(?:m|f|male|female|पुरुष|महिला))?\s*$",
    re.I,
)
NOTE_AGE = re.compile(
    rf"(?P<prefix>(?i:\b(?:(?:{'|'.join(ROLE_PREFIXES)})[ \t]+)?(?:age(?:[ \t]*(?:/[ \t]*sex|\([ \t]*(?:yrs?|years?)[ \t]*\)))?|umar)|(?:आयु|उम्र|वय))[ \t]*[:：=][ \t]*)(?P<age>{_D}{{1,3}})(?!{_D}|[-–]{_D}|\.)"
    rf"|(?<![\w.-])(?P<inline>{_D}{{1,3}})(?=(?:[ \t]*(?i:y|yrs?|years?)|[ \t]*वर्ष)[ \t]*/[ \t]*(?:(?i:m|f|male|female)\b|(?:पुरुष|महिला))|[ \t]*/[ \t]*(?i:m|f)\b)"
)


@lru_cache(maxsize=1024)
def is_age_label(label: str) -> bool:
    return label in AGE_ROOTS or any(label.startswith(p) and label[len(p):] in AGE_ROOTS for p in ROLE_PREFIXES)


@lru_cache(maxsize=1024)
def is_district_label(label: str) -> bool:
    return label in DISTRICT_ROOTS or any(label.startswith(p) and label[len(p):] in DISTRICT_ROOTS for p in ROLE_PREFIXES)


@lru_cache(maxsize=1024)
def is_date_label(label: str) -> bool:
    clean = re.sub(r"(?:mmddyyyy|ddmmyyyy|yyyymmdd)$", "", label)
    if any(clean.startswith(p) for p in ROLE_PREFIXES):
        for p in ROLE_PREFIXES:
            if clean.startswith(p) and clean[len(p):]:
                clean = clean[len(p):]
                break
    return clean in DATE_LABELS or any(
        clean == f"{ev}{suf}" for ev in DATE_EVENTS for suf in ("dt", "date", "datetime", "on", "at")
    )


MONTH_NAMES = {name[:3].casefold(): i for i, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
MONTH_WORD = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
NAMED_DATE = re.compile(rf"(?i)\b(?:\d{{1,2}}[ -]{MONTH_WORD}|{MONTH_WORD}[ -]\d{{1,2}}),?[ -]\d{{4}}\b")


def parse_date(value: str, month_first=False) -> dt.date:
    value = ascii_digits(value)
    if value[0].isalpha() or any(c.isalpha() for c in value):
        first, second, year = re.split(r"[, \-]+", value)
        month, day = (first, second) if first.isalpha() else (second, first)
        return dt.date(int(year), MONTH_NAMES[month[:3].casefold()], int(day))
    first, middle, last = (int(part) for part in re.split(r"[-./]", value))
    if first > 31:
        return dt.date(first, middle, last)
    if middle > 12 or month_first and first <= 12:
        return dt.date(last, first, middle)
    return dt.date(last, middle, first)


def shift_dates(text: str, key: str, month_first=False) -> str:
    if not SHIFT_DATES_ENABLED:
        return text

    def replace(match):
        try:
            return shift_date(parse_date(match[0], month_first), key).isoformat()
        except (ValueError, OverflowError):
            return match[0]

    return NAMED_DATE.sub(replace, DATE_TOKEN.sub(replace, text))


def month_first_dates(text: str) -> bool:
    for match in DATE_TOKEN.finditer(text):
        parts = re.split(r"[-./]", ascii_digits(match[0]))
        if len(parts[0]) < 4:
            if int(parts[0]) > 12:
                return False
            if int(parts[1]) > 12:
                return True
    return False


def band_age(value: str, index=None, key=None, areas=()) -> str:
    if not GENERALIZE_AGES_ENABLED:
        return value
    return re.sub(
        rf"^(\s*)({_D}{{1,3}})(?!{_D}|[-–]{_D})",
        lambda m: m[1] + (index.age_interval(int(ascii_digits(m[2])), key, areas) if index else age_band(int(ascii_digits(m[2])))),
        value,
        count=1,
    )


def band_note_ages(text: str, index=None, key=None, areas=()) -> str:
    if not GENERALIZE_AGES_ENABLED:
        return text

    def replace(match: re.Match) -> str:
        raw = int(ascii_digits(match["age"] or match["inline"]))
        banded = index.age_interval(raw, key, areas) if index else age_band(raw)
        return f"{match['prefix']}{banded}" if match["age"] else banded

    out = NOTE_AGE.sub(replace, text)
    if any(sep in out for sep in (":", "=", "：")):
        def dyn_age(m: re.Match) -> str:
            if not dynamic_is_age_label(m["label"]):
                return m[0]
            banded = band_age(m["value"], index, key, areas)
            return m[0][:-len(m["value"])] + banded
        out = DYNAMIC_NOTE_FIELD.sub(dyn_age, out)
    return out


def redact_note_field(match: re.Match) -> str:
    label = field_label(match["label"])
    if label in EXTRA_PRESERVE_FIELDS:
        return match[0]
    kind = resolve_field_kind(match["label"]) or "NAME"
    if not _category_enabled(kind):
        return match[0]
    Stats.record_entity(kind)
    return match[0][:-len(match["value"])] + f"[{kind}]"


def redact_dynamic_note_field(match: re.Match) -> str:
    val = match["value"].strip()
    if not val or re.fullmatch(r"\[[A-Z_]+\]|PSN-[A-Z0-9]+", val):
        return match[0]
    kind = dynamic_field_kind(match["label"])
    if not kind or not _category_enabled(kind):
        return match[0]
    Stats.record_entity(kind)
    return match[0][:-len(match["value"])] + f"[{kind}]"


def _apply_custom_note_rules(text: str) -> str:
    if EXTRA_REDACT_FIELDS and any(sep in text for sep in (":", "=", "：")):
        # Match user-configured custom field labels in free text
        for raw_field in _parse_list(POLICY.get("extra_redact_fields")):
            rx = re.compile(
                r"(?im)(?:^|[ \t]{2,}|(?<=[;,|]))[ \t]*"
                + re.escape(raw_field).replace(r"\ ", r"[ _\t-]*")
                + r"[ \t]*[:：=][ \t]*(?P<val>[^\r\n;|]+)"
            )
            def _rep(m):
                Stats.record_entity("CUSTOM")
                return m[0][:-len(m["val"])] + "[CUSTOM]"
            text = rx.sub(_rep, text)
    if EXTRA_REDACT_TERMS:
        for term in EXTRA_REDACT_TERMS:
            pattern = re.compile(rf"(?i)(?<!\w){re.escape(term)}(?!\w)")
            text, n = pattern.subn("[CUSTOM]", text)
            Stats.record_entity("CUSTOM", n)
    if EXTRA_REDACT_REGEX is not None:
        text, n = EXTRA_REDACT_REGEX.subn("[CUSTOM]", text)
        Stats.record_entity("CUSTOM", n)
    return text


INVISIBLE = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff\u00ad")
LOOKALIKES = str.maketrans("АВЕКМНОРСТХаеорсхуΑΒΕΖΗΙΚΜΝΟΡΤΥΧο",
                           "ABEKMHOPCTXaeopcxyABEZHIKMNOPTYXo")
MIXED_WORD = re.compile(r"[^\W\d_]+")
ESCAPED_CHAR = re.compile(r"\\u([0-9a-fA-F]{4})")
ARMOR = re.compile(r"(?<![A-Za-z0-9+/])(?:[A-Fa-f0-9]{12,}|[A-Za-z0-9+/]{12,}={0,2})(?![A-Za-z0-9+/])")


def readable(text):
    """Make a detection copy. Preserve the original if no private span is found."""
    for _ in range(3):
        before = text
        if "&" in text:
            text = html.unescape(text)
        if "%" in text:
            try:
                text = urllib.parse.unquote(text, errors="strict")
            except UnicodeDecodeError:
                pass
        if "\\u" in text:
            text = ESCAPED_CHAR.sub(lambda m: chr(int(m[1], 16)) if not
                                    0xD800 <= int(m[1], 16) <= 0xDFFF else m[0], text)
        if before == text:
            break
    if text.isascii():
        return text
    text = text.translate(INVISIBLE)
    if re.search(r"[\uff01-\uff5e]", text):
        text = re.sub(r"[\uff01-\uff5e]+", lambda m: unicodedata.normalize("NFKC", m[0]), text)
    if re.search(r"[\u0370-\u052f]", text):
        text = MIXED_WORD.sub(lambda m: m[0].translate(LOOKALIKES)
                              if re.search("[a-zA-Z]", m[0]) else m[0], text)
    return text


def clean_text(text: str) -> str:
    if not text:
        return text
    def scan_encoded(match):
        token = match[0]
        if len(token) > 131072:
            return token
        try:
            if re.fullmatch(r"(?:[a-fA-F0-9]{2})+", token):
                raw = bytes.fromhex(token)
            else:
                padded = token + "=" * (-len(token) % 4) if len(token) % 4 != 1 else token
                raw = base64.b64decode(padded, validate=True)
            decoded = raw.decode("utf-8")
        except ValueError:
            return token
        if not decoded or any(not c.isprintable() and c not in "\t\r\n" for c in decoded):
            return token
        plain = readable(decoded)
        cleaned = redact_plain(plain)
        return cleaned if cleaned != plain else token

    # Plain clinical codes, UUIDs and ordinary prose retain their input spelling.
    normalized = readable(text)
    candidate = ARMOR.sub(scan_encoded, normalized) if len(normalized) >= 12 else normalized
    safe = redact_plain(candidate)
    if safe != candidate or candidate != normalized:
        return safe
    return text


def redact_plain(text: str) -> str:
    """Redact labeled fields before scanning for standalone identifiers."""
    if any(sep in text for sep in (":", "=", "：")):
        text = NOTE_FIELD.sub(redact_note_field, text)
        text = DYNAMIC_NOTE_FIELD.sub(redact_dynamic_note_field, text)
    text = redact_care_of_relative(text)
    if (" " in text or "\t" in text) and _category_enabled("NAME"):
        if _category_enabled("RELATIVE"):
            text, n = RELATIVE_NAME.subn(r"\g<prefix>[RELATIVE]", text)
            Stats.record_entity("RELATIVE", n)
        for pattern in CONTEXT_PATTERNS:
            text, n = pattern.subn(r"\g<prefix>[NAME]", text)
            Stats.record_entity("NAME", n)
        if "report" in text.casefold():
            def subject(match):
                if match[1].casefold() not in VOCAB.given_names:
                    return match[0]
                Stats.record_entity("NAME")
                return match[0][:-len(match[1])] + "[NAME]"
            text = REPORT_SUBJECT.sub(subject, text)
    if _category_enabled("MRN") and VOCAB.chart_ids and any(c.isdigit() for c in text):
        def chart(match):
            if identity_id(match[0]) not in VOCAB.chart_ids:
                return match[0]
            Stats.record_entity("MRN")
            return "[MRN]"
        text = ID_TOKEN.sub(chart, text)
    for kind, rx in PATTERNS:
        if _category_enabled(kind):
            text, n = rx.subn(f"[{kind}]", text)
            Stats.record_entity(kind, n)
    text = _apply_custom_note_rules(text)
    return VOCAB.redact(text)


@lru_cache(maxsize=2048)
def sensitive_label(label: str) -> bool:
    if not HASH_FILENAMES_ENABLED:
        return False
    probe = readable(label)
    return bool(ID_TOKEN.search(probe.upper())) or clean_text(label) != label or bool(
        re.search(r"(?<!\d)\d{10,18}(?!\d)", ascii_digits(probe))
    )


def sensitive_filename(label: str) -> bool:
    if sensitive_label(label):
        return True
    tokens = {match[0].casefold() for match in WORDS.finditer(readable(label))}
    # A single patient-name token in a filename can identify a record. Requiring
    # a complete name misses names followed by words such as "followup".
    return bool(HASH_FILENAMES_ENABLED and tokens & VOCAB.name_tokens)


def release_path(relative: Path) -> str:
    folders = [private_label(part) if sensitive_filename(part) else part for part in relative.parts[:-1]]
    name = private_label(relative.stem) + relative.suffix if sensitive_filename(relative.stem) else relative.name
    return "/".join([*folders, name])


DOCTOR_CONTEXTS = {
    "doctor", "refdoctor", "physician", "consultant", "referredby", "reviewedby",
    "doctorname", "practitionername", "attendingconsultant", "prescriber", "clinician",
}


def clean_value(value, kind=None, *, context="", date_key=None, records_by_id=None, index=None, patient_key=None, areas=()):
    if records_by_id and id(value) in records_by_id:
        return records_by_id[id(value)]
    if isinstance(value, list):
        return [
            clean_value(item, kind, context=context, date_key=date_key, records_by_id=records_by_id,
                        index=index, patient_key=patient_key, areas=areas)
            for item in value
        ]
    if isinstance(value, dict):
        nested = NESTED_FIELDS.get(context, {})
        whole_name = (kind == "NAME" and context != "patient") or (
            kind == "RELATIVE" and context != "guardian"
        )
        attachment = context == "attachment" or "contentType" in value or value.get("encoding") == "base64"
        cleaned = {}
        for key, item in value.items():
            label = field_label(key)
            if label in EXTRA_PRESERVE_FIELDS:
                child_kind = None
            else:
                child_kind = kind if whole_name else nested.get(label) or resolve_field_kind(key)
            if context == "byname" and isinstance(item, str) and identity_id(item):
                child_kind = "MRN"
            new_key = private_label(key) if (HASH_FILENAMES_ENABLED and (context in PRIVATE_MAPS or sensitive_filename(key))) else key
            if new_key in cleaned:
                raise ValueError("key_collision")
            if (attachment and label in ATTACHMENT_FIELDS or label in {"base64", "contentbase64", "database64", "attachmentbase64"}) and isinstance(item, str):
                if item:
                    Stats.record_entity("ATTACHMENT")
                cleaned[new_key] = ""
            else:
                cleaned[new_key] = clean_value(
                    item, child_kind, context=label, date_key=date_key, records_by_id=records_by_id,
                    index=index, patient_key=patient_key, areas=areas,
                )
        return cleaned
    if context in EXTRA_PRESERVE_FIELDS:
        return value
    if kind and _category_enabled(kind) and type(value) in (str, int, float) and value != "":
        Stats.record_entity(kind)
        return f"[{kind}]" if isinstance(value, str) else type(value)(0)
    if dynamic_is_age_label(context) and type(value) in (str, int) and GENERALIZE_AGES_ENABLED:
        match = AGE_VALUE.fullmatch(str(value))
        if match:
            age = int(ascii_digits(match[1]))
            if 0 <= age <= 125:
                return index.age_interval(age, patient_key, areas) if index else age_band(age)
    if not isinstance(value, str):
        return value
    if PRESERVE_DOCTORS_ENABLED and context in DOCTOR_CONTEXTS:
        return value
    if is_age_label(context):
        return band_age(value, index, patient_key, areas)
    if date_key and is_date_label(context):
        return shift_dates(value, date_key)
    safe = clean_text(value)
    if date_key and re.search(r"\d{4}-\d\d-\d\d[Tt]\d\d:", safe):
        safe = shift_dates(safe, date_key)
    return band_note_ages(safe, index, patient_key, areas) if date_key else safe


# --------------------------------------------------------------------------- linkage
IDENTITY_CONTEXT = {"patient", "patientref", "patientdetails", "patientidentifiers", "patientidentification", "contact", "ids", "demographics", "identifiers"}
IDENTITY_KINDS = {"MRN", "ENCOUNTER", "NAME", "RELATIVE", "PHONE", "DOB", "NATIONAL_ID", "EMAIL", "ADDRESS"}
VILLAGE_LABELS = {field_label(k) for k in ("village", "gaon", "ग्राम", "village/mohalla", "gram/mohalla")}
CALLBACK = re.compile(r"(?i)\b(?:call(?:\s+(?:karo|back|at|on))?|mobile|phone)\s*[:=-]?\s*"
                      r"(?P<number>(?:(?:\+|00)?(?:91|९१)[\s().-]*)?0?[6-9६-९][\s().-]*\d{4}(?:[\s().-]*\d){5})(?!\d)")
REPORT_SUBJECT = re.compile(r"(?i)\breport\s+(?:of|for)\s+([^\W\d_]+)")


def identity_id(value: str) -> str | None:
    token = re.sub(r"[\s_./-]", "", ascii_digits(value)).upper()
    if re.fullmatch(r"\d{7,18}", token):
        return token
    if re.fullmatch(r"[A-Z][A-Z0-9]{3,47}", token) and sum(c.isdigit() for c in token) >= 2:
        return token
    return None


def identity_fields(record, depth=0, context=""):
    if isinstance(record, str):
        for match in FRAGMENTED_RELATION.finditer(readable(record)):
            yield "patient name", "NAME", match["patient"].strip()
            yield "relative name", "RELATIVE", match["relative"].strip()
        seen_spans = set()
        for match in NOTE_FIELD.finditer(record):
            seen_spans.add(match.span())
            label = field_label(match["label"])
            yield label, resolve_field_kind(match["label"]) or "NAME", match["value"].strip()
        if any(sep in record for sep in (":", "=", "：")):
            for match in DYNAMIC_NOTE_FIELD.finditer(record):
                if match.span() in seen_spans:
                    continue
                kind = dynamic_field_kind(match["label"])
                if kind in IDENTITY_KINDS:
                    yield field_label(match["label"]), kind, match["value"].strip()
    elif isinstance(record, dict) and depth < 4:
        for raw_label, value in record.items():
            label = field_label(raw_label)
            kind = NESTED_FIELDS.get(context, {}).get(label) or resolve_field_kind(raw_label)
            if isinstance(value, str):
                for match in FRAGMENTED_RELATION.finditer(readable(value)):
                    yield "patient name", "NAME", match["patient"].strip()
                    yield "relative name", "RELATIVE", match["relative"].strip()
            if label in IDENTITY_CONTEXT and isinstance(value, dict):
                yield from identity_fields(value, depth + 1, label)
            elif label == "name" and isinstance(value, dict):
                for spelling in (value.get("local"), " ".join(str(value.get(k, "")) for k in ("first", "last"))):
                    if spelling:
                        yield "name", "NAME", spelling.strip()
            elif type(value) in (str, int) and (kind in IDENTITY_KINDS or label in {"name", "birthdate"}):
                yield label, kind or ("NAME" if label == "name" else "DOB"), str(value).strip()


def demographic_fields(record, depth=0):
    if isinstance(record, str):
        for match in NOTE_AGE.finditer(record):
            yield "AGE", int(ascii_digits(match["age"] or match["inline"]))
        if any(sep in record for sep in (":", "=", "：")):
            for match in DYNAMIC_NOTE_FIELD.finditer(record):
                if dynamic_is_age_label(match["label"]):
                    if am := AGE_VALUE.match(match["value"].strip()):
                        yield "AGE", int(ascii_digits(am[1]))
                elif dynamic_is_district_label(match["label"]) and "[" not in match["value"] and match["value"].strip():
                    yield "AREA", match["value"].strip().casefold()
    elif isinstance(record, dict) and depth < 3:
        for raw_label, value in record.items():
            label = field_label(raw_label)
            if label in IDENTITY_CONTEXT | {"address"} and isinstance(value, dict):
                yield from demographic_fields(value, depth + 1)
            elif isinstance(value, str) and dynamic_is_district_label(raw_label) and "[" not in value and value.strip():
                yield "AREA", value.strip().casefold()
            elif isinstance(value, (str, int)) and dynamic_is_age_label(raw_label):
                if match := AGE_VALUE.match(str(value)):
                    yield "AGE", int(ascii_digits(match[1]))


def evidence(record, month_first=False):
    fields = defaultdict(set)
    names = {}
    def scan_phone_values(value):
        if isinstance(value, str):
            probe = readable(value)
            for match in PHONE_PATTERN.finditer(probe):
                digits = re.sub(r"\D", "", ascii_digits(match[0]))
                if len(digits) >= 10:
                    fields["PHONE"].add(digits[-10:])
        elif isinstance(value, dict):
            for child in value.values():
                scan_phone_values(child)
        elif isinstance(value, list):
            for child in value:
                scan_phone_values(child)

    scan_phone_values(record)
    if isinstance(record, str):
        record = readable(record)
        fields["GIVEN"].update(canonical_person_name(m[1]) for m in REPORT_SUBJECT.finditer(record))
        for pattern in (TEXT_NOTE_SUBJECT, TEXT_LEADING_CONTACT):
            for match in pattern.finditer(record):
                fields["NAME"].add(match["name"].strip())
                if match.groupdict().get("alias"):
                    fields["NAME"].add(match["alias"].strip())
    context = "patients" if isinstance(record, dict) and patient_record(record) else ""
    for label, kind, value in identity_fields(record, context=context):
        value = readable(value)
        if kind in {"MRN", "ENCOUNTER"}:
            if token := identity_id(value):
                fields[kind].add(token)
        elif kind == "NAME" and value:
            if label in {"firstname", "lastname"}:
                names[label] = value
            else:
                fields[kind].add(value)
        elif kind == "RELATIVE" and value:
            fields[kind].add(value)
        elif kind == "ADDRESS" and label in VILLAGE_LABELS and value:
            fields["VILLAGE"].add(value.casefold())
        elif kind == "EMAIL" and re.fullmatch(r"[\w.+-]+@[\w.-]+", value):
            fields["EMAIL"].add(value.casefold())
        elif kind in {"PHONE", "NATIONAL_ID"}:
            digits = re.sub(r"\D", "", ascii_digits(value))
            if kind == "PHONE" and len(digits) in (10, 11, 12):
                fields[kind].add(digits[-10:])
            elif kind == "NATIONAL_ID" and len(digits) in (12, 14):
                fields[kind].add(digits)
        elif kind == "DOB" and (DATE_TOKEN.fullmatch(value) or NAMED_DATE.fullmatch(value)):
            try:
                fields[kind].add(parse_date(value, month_first or "mmddyyyy" in label).isoformat())
            except ValueError:
                pass
    if len(names) == 2:
        fields["NAME"].add(names["firstname"] + " " + names["lastname"])
    for kind, value in demographic_fields(record):
        fields[kind].add(value)
    for area in fields["AREA"]:
        for age in fields["AGE"]:
            fields["AREA_AGE"].add((area, age))
    return fields


def identity_pairs(fields):
    for national in fields["NATIONAL_ID"]:
        yield ("national", national)
    for phone in fields["PHONE"]:
        for dob in fields["DOB"]:
            yield ("phone-dob", phone, dob)
    for name in fields["NAME"]:
        words = name.casefold().split()
        if len(words) >= 2:
            canonical_raw = " ".join(words)
            for dob in fields["DOB"]:
                yield ("name-dob", canonical_raw, dob)
            for phone in fields["PHONE"]:
                yield ("name-phone", canonical_raw, phone)
        canon = canonical_person_name(name)
        if len(canon.split()) >= 2:
            for dob in fields["DOB"]:
                yield ("cname-dob", canon, dob)
            for phone in fields["PHONE"]:
                yield ("cname-phone", canon, phone)


def supporting_clues(fields, *, lookup=False):
    """Secondary clues can attach a record to a chart, never join two charts."""
    names = {canonical_person_name(name) for name in fields["NAME"]}
    given = fields["GIVEN"] | {name.split()[0] for name in names if len(name.split()) >= 2}
    relative_names = {canonical_person_name(name) for name in fields["RELATIVE"]}
    for name in names:
        for relative in relative_names:
            if name and relative:
                # This pair is only an attachment clue. If it identifies more
                # than one chart, resolve() abstains instead of merging charts.
                yield ("name-relative-given", name.split()[0], relative.split()[0])
    for phone in fields["PHONE"]:
        for first in given:
            if first:
                yield ("callback-given", phone, first)
    for email in fields["EMAIL"]:
        yield ("email", email)
    for name in names:
        if len(name.split()) >= 2:
            for village in fields["VILLAGE"]:
                for age in fields["AGE"]:
                    for nearby in (range(age - 1, age + 2) if lookup else (age,)):
                        yield ("name-village-age", name, village, nearby)


def merge_age_intervals(people_ages, base: int, max_span: int, min_group: int) -> list[tuple[int, int]]:
    """Merge sparse or longitudinal adjacent age bins in a district up to max_span."""
    bins = defaultdict(set)
    for pid, age in people_ages:
        if age >= 0:
            lo = (age // base) * base
            bins[(lo, lo + base - 1)].add(pid)
    intervals = [[lo, hi, set(pids)] for (lo, hi), pids in sorted(bins.items())]
    i = 0
    while i < len(intervals) - 1:
        if intervals[i][2] & intervals[i + 1][2] and intervals[i + 1][1] - intervals[i][0] + 1 <= max_span:
            intervals[i][1] = intervals[i + 1][1]
            intervals[i][2] |= intervals[i + 1][2]
            intervals.pop(i + 1)
        else:
            i += 1
    while len(intervals) > 1:
        candidates = []
        for idx, (lo, hi, pids) in enumerate(intervals):
            if len(pids) >= min_group:
                continue
            for nb in (idx - 1, idx + 1):
                if 0 <= nb < len(intervals):
                    n_lo, n_hi = min(lo, intervals[nb][0]), max(hi, intervals[nb][1])
                    span = n_hi - n_lo + 1
                    merged = pids | intervals[nb][2]
                    if span <= max_span and len(merged) > len(pids):
                        candidates.append((span, len(intervals[nb][2]) >= min_group, len(merged), min(idx, nb)))
        if not candidates:
            break
        _, _, _, left = min(candidates)
        intervals[left][1] = intervals[left + 1][1]
        intervals[left][2] |= intervals[left + 1][2]
        intervals.pop(left + 1)
    return [(lo, hi) for lo, hi, _ in intervals]


class IdentityIndex:
    """Match exact chart IDs or independent corroborating fields."""

    def __init__(self):
        self.roots = {}
        self.birth_dates = defaultdict(set)
        self.phones_by_mrn = defaultdict(set)
        self.national_ids = defaultdict(lambda: defaultdict(set))
        self.pairs = defaultdict(set)
        self.support = defaultdict(set)
        self.encounters = defaultdict(set)
        self.ages_by_area = defaultdict(set)
        self.ages_by_mrn = defaultdict(set)
        self.areas_by_mrn = defaultdict(set)
        self.patient_areas = defaultdict(set)
        self.age_bands = {}

    def observe(self, fields):
        VOCAB.chart_ids.update(fields["MRN"])
        for relative in fields["RELATIVE"]:
            VOCAB.add_relative(relative)
        if fields["MRN"] and any(fields[kind] for kind in ("NAME", "DOB", "PHONE", "NATIONAL_ID")):
            for name in fields["NAME"]:
                VOCAB.add(name)
        if not fields["MRN"]:
            return
        # Multiple patient identifiers in one record are aliases for that
        # record's person (e.g. a local UHID plus a longitudinal MRN). Index
        # them under one deterministic root; conflicting records still abstain
        # later when their demographics or national identifiers disagree.
        keys = sorted(fields["MRN"])
        for key in keys:
            self.roots.setdefault(key, key)
        roots = {self.root(key) for key in keys}
        mrn = min(roots)
        for root in roots:
            if root == mrn:
                continue
            self.roots[root] = mrn
            self.birth_dates[mrn].update(self.birth_dates[root])
            self.phones_by_mrn[mrn].update(self.phones_by_mrn[root])
            self.ages_by_mrn[mrn].update(self.ages_by_mrn[root])
            self.areas_by_mrn[mrn].update(self.areas_by_mrn[root])
            for size, values in self.national_ids[root].items():
                self.national_ids[mrn][size].update(values)
        self.roots[mrn] = mrn
        for key in keys:
            self.roots[key] = mrn
        self.birth_dates[mrn].update(fields["DOB"])
        self.phones_by_mrn[mrn].update(fields["PHONE"])
        for national in fields["NATIONAL_ID"]:
            self.national_ids[mrn][len(national)].add(national)
        for pair in identity_pairs(fields):
            self.pairs[pair].add(mrn)
        for clue in supporting_clues(fields):
            self.support[clue].add(mrn)
        for encounter in fields["ENCOUNTER"]:
            self.encounters[encounter].add(mrn)
        self.ages_by_mrn[mrn].update(fields["AGE"])
        self.areas_by_mrn[mrn].update(fields["AREA"])
        for area, age in fields["AREA_AGE"]:
            self.ages_by_area[area].add((mrn, age))

    def root(self, key):
        while key != self.roots[key]:
            key = self.roots[key]
        return key

    def finish(self):
        for pair, ids in sorted(self.pairs.items()):
            roots = {self.root(mrn) for mrn in ids}
            if len(roots) < 2:
                continue
            # Large groups are merged only when the shared clue is a jointly
            # identifying pair (or national ID). Shared names or callback
            # numbers alone are too collision-prone to merge a group.
            if len(roots) > 2 and pair[0] not in {
                "national", "phone-dob", "name-phone", "cname-phone"
            }:
                continue
            first = min(roots)
            for candidate in sorted(roots - {first}):
                first, second = self.root(first), self.root(candidate)
                if first == second:
                    continue
                known, other = self.birth_dates[first], self.birth_dates[second]
                known_phones, other_phones = self.phones_by_mrn[first], self.phones_by_mrn[second]
                identities, others = self.national_ids[first], self.national_ids[second]
                conflicting_phones = known_phones and other_phones and known_phones.isdisjoint(other_phones)
                # Disjoint observed phones block soft name/DOB matches. A shared
                # national ID can still link a patient whose phone has changed.
                if (
                    (known and other and known != other)
                    or conflicting_phones and pair[0] != "national"
                    or any(len(identities[size] | others[size]) > 1 for size in identities.keys() & others.keys())
                ):
                    continue
                self.roots[second] = first
                known.update(other)
                known_phones.update(other_phones)
                for size, values in others.items():
                    identities[size].update(values)
        patient_ages = defaultdict(set)
        for mrn, ages in self.ages_by_mrn.items():
            patient_ages[self.root(mrn)].update(ages)
        for mrn, areas in self.areas_by_mrn.items():
            self.patient_areas[self.root(mrn)].update(areas)
        base = max(1, int(POLICY.get("age_band_years", 5)))
        max_span = max(base, int(POLICY.get("age_band_max_years", 50)))
        min_group = max(1, int(POLICY.get("age_k_anonymity", 2)))
        for area, people in self.ages_by_area.items():
            covered_pids = {self.root(mrn) for mrn, _ in people}
            pooled = {(pid, age) for pid in covered_pids for age in patient_ages[pid]}
            pooled |= {(self.root(mrn), age) for mrn, age in people}
            self.age_bands[area] = merge_age_intervals(pooled, base, max_span, min_group)

    def age_interval(self, age: int, key=None, areas=()) -> str:
        if not GENERALIZE_AGES_ENABLED:
            return str(age)
        if age < 0:
            return str(age)
        search_areas = sorted(areas) if areas else sorted(self.patient_areas.get(key, ()))
        best = None
        for area in search_areas:
            for lo, hi in self.age_bands.get(area, ()):
                if lo <= age <= hi:
                    if best is None or (hi - lo) > (best[1] - best[0]):
                        best = (lo, hi)
                    break
        return f"{best[0]}-{best[1]}" if best is not None else age_band(age)

    def resolve(self, record, fields):
        candidates = set(fields["MRN"])
        if not candidates:
            for encounter in fields["ENCOUNTER"]:
                candidates.update(self.encounters.get(encounter, ()))
            for pair in identity_pairs(fields):
                candidates.update(self.pairs.get(pair, ()))
            for clue in supporting_clues(fields, lookup=True):
                candidates.update(self.support.get(clue, ()))
        if not candidates and isinstance(record, str):
            for match in ID_TOKEN.finditer(record):
                token = identity_id(match[0])
                if token in self.roots:
                    candidates.add(token)
                candidates.update(self.encounters.get(token, ()))
        roots = {self.root(mrn) for mrn in candidates if mrn in self.roots}
        if not roots and not candidates and len(fields["NAME"]) == 1 and len(fields["PHONE"]) == 1:
            # A name+phone pair can identify a chartless note. When that pair
            # maps to conflicting charts above, this conservative fallback is
            # skipped rather than inventing a link.
            name = canonical_person_name(next(iter(fields["NAME"])))
            phone = next(iter(fields["PHONE"]))
            if len(name.split()) >= 2:
                return f"chartless|{name}|{phone}"
        if len(roots) != 1:
            return None
        key = next(iter(roots))
        if len(self.birth_dates[key]) > 1 or any(len(v) > 1 for v in self.national_ids[key].values()):
            return None
        has_direct_chart = bool(fields["MRN"] or fields["ENCOUNTER"])
        if (
            not has_direct_chart
            and fields["PHONE"]
            and self.phones_by_mrn[key]
            and fields["PHONE"].isdisjoint(self.phones_by_mrn[key])
        ):
            return None
        if fields["DOB"] and self.birth_dates[key] and fields["DOB"] != self.birth_dates[key]:
            return None
        for national in fields["NATIONAL_ID"]:
            known = self.national_ids[key].get(len(national))
            if known and national not in known:
                return None
        return key


def redact_known(text: str, fields) -> str:
    if not _category_enabled("NAME"):
        return text
    for name in sorted(fields["NAME"], key=lambda n: (-len(n), n)):
        if len(name.split()) > 1 and len(name) > 4:
            if PRESERVE_DOCTORS_ENABLED:
                pattern = rf"(?i)(?<![\w])(?<!Dr\. )(?<!Dr )(?<!डॉ\. ){re.escape(name)}(?![\w])"
            else:
                pattern = rf"(?i)(?<![\w]){re.escape(name)}(?![\w])"
            text, count = re.subn(pattern, "[NAME]", text)
            Stats.record_entity("NAME", count)
    return text


def redact_care_of_relative(text: str) -> str:
    """Mask a person after care-of shorthand without masking complaint-of text.

    Explicit relative-name fields are strongest evidence. When such a field is
    absent, a capitalized person-like value after C/O is masked unless it is a
    known clinical term (e.g. "C/O Fever" or "C/O Parkinson's disease").
    The rule is confined to the care-of phrase; clinician mentions elsewhere
    remain untouched.
    """
    if not text or not _category_enabled("RELATIVE"):
        return text

    def replace(match):
        # In clinical shorthand, K/C/O means "known case of". Its trailing
        # C/O must not be interpreted as a relative field. Allow spaces around
        # the slash as they appear in some typed discharge notes.
        if KNOWN_CASE_OF_PREFIX.search(text[max(0, match.start("prefix") - 16):match.start("prefix")]):
            return match[0]
        name = match["name"].strip()
        normalized = " ".join(m[0].casefold() for m in WORDS.finditer(name))
        if not normalized or normalized in {"dr", "doctor", "consultant"} or normalized.startswith(("dr ", "doctor ", "consultant ")):
            return match[0]
        if normalized in CARE_OF_CLINICAL_WORDS or any(
            word in CARE_OF_CLINICAL_WORDS for word in normalized.split()
        ):
            return match[0]
        explicit_relative = normalized in VOCAB.relative_names
        # A one-word complaint is usually lower-case; preserve the known common
        # complaint words even when the source capitalizes them after a colon.
        person_like = bool(name and name[0].isupper())
        if explicit_relative or person_like:
            Stats.record_entity("RELATIVE")
            return match["prefix"] + "[RELATIVE]"
        return match[0]

    return CARE_OF_PERSON.sub(replace, text)


# --------------------------------------------------------------------------- I/O
def decode(raw: bytes) -> str | None:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="strict")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if len(raw) >= 8 and len(raw) % 2 == 0:
        sample = raw[:1024]
        for offset, encoding in ((1, "utf-16-le"), (0, "utf-16-be")):
            if sample[offset::2].count(0) > len(sample) // 5 and not sample[1-offset::2].count(0):
                return raw.decode(encoding)
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate_json_key")
    return result


def invalid_number(_):
    raise ValueError("invalid_json_number")


def patient_record(value):
    if not isinstance(value, dict):
        return False
    labels = {field_label(key) for key, item in value.items() if not isinstance(item, list)}
    kinds = {resolve_field_kind(key) for key, item in value.items() if not isinstance(item, list)}
    return bool(kinds & {"MRN", "NATIONAL_ID", "NAME"} or "demographics" in labels
                or "name" in labels and kinds & {"DOB", "PHONE", "EMAIL"})


def json_person_key(value):
    if not isinstance(value, str):
        return None
    candidate = re.sub(r"[_-]+", " ", value).strip()
    words = [match[0] for match in WORDS.finditer(candidate)]
    return candidate if 2 <= len(words) <= 5 and " ".join(words).casefold() == candidate.casefold() else None


def json_records(data, path=()):
    if isinstance(data, list):
        for index, item in enumerate(data):
            yield from json_records(item, (*path, index))
    elif isinstance(data, dict):
        if patient_record(data):
            yield path, data, None
            return
        for key, item in data.items():
            if isinstance(item, dict) and (name_hint := json_person_key(key)):
                keyed = dict(item)
                keyed["Patient Name"] = name_hint
                keyed_fields = evidence(keyed)
                if keyed_fields["NAME"] and any(
                    keyed_fields[kind] for kind in ("MRN", "DOB", "PHONE", "NATIONAL_ID")
                ):
                    yield (*path, key), item, name_hint
                    continue
            if isinstance(item, (list, dict)):
                yield from json_records(item, (*path, key))


def is_bundle(value) -> bool:
    return isinstance(value, dict) and value.get("resourceType") == "Bundle"


def bundle_entries(bundle):
    entries = bundle.get("entry", [])
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict) for entry in entries
    ):
        raise ValueError("invalid_fhir_entries")
    return entries


FHIR_DATE_ONLY = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")
FHIR_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
FHIR_INSTANT_FIELDS = {"timestamp", "lastupdated"}
FHIR_DATE_FIELDS = {"birthdate", "deceaseddate"}
FHIR_DATE_TIME_FIELDS = {
    "authoredon", "effectivedatetime", "issued", "occurrencedatetime",
    "performeddatetime", "recorded", "recordeddate", "recordeddatetime",
    "deceaseddatetime", "onsetdatetime", "abatementdatetime",
    "admitteddate", "dischargeddate", "dateofbirth", "dateofadmission",
    "dateofdischarge", "admissiondate", "dischargedate", "visitdate",
    "start", "end",
}


def _valid_fhir_date(value, kind):
    """Validate FHIR date primitives before any transformation can hide errors."""
    if not isinstance(value, str):
        return False
    if kind == "date":
        if not FHIR_DATE_ONLY.fullmatch(value):
            return False
        parts = [int(part) for part in value.split("-")]
        try:
            if len(parts) == 1:
                dt.date(parts[0], 1, 1)
            elif len(parts) == 2:
                dt.date(parts[0], parts[1], 1)
            else:
                dt.date(*parts)
        except ValueError:
            return False
        return True
    if kind == "dateTime" and FHIR_DATE_ONLY.fullmatch(value):
        return _valid_fhir_date(value, "date")
    if not FHIR_DATE_TIME.fullmatch(value):
        return False
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    if kind == "instant" and ("T" not in value or not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", value)):
        return False
    return True


def validate_fhir_dates(bundle):
    """Quarantine a Bundle with malformed FHIR date/dateTime/instant primitives.

    This is intentionally a focused primitive check, not full profile validation.
    It catches impossible calendar dates and malformed timestamps before the
    release sanitizer drops or shifts those values.
    """
    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            normalized = field_label(key)
            kind = None
            if normalized in FHIR_INSTANT_FIELDS:
                kind = "instant"
            elif normalized in FHIR_DATE_FIELDS:
                kind = "date"
            elif normalized in FHIR_DATE_TIME_FIELDS or normalized.endswith("datetime"):
                kind = "dateTime"
            elif normalized == "date":
                # FHIR resources use both date and dateTime for fields named date.
                kind = "dateTime"
            if kind and item is not None and not _valid_fhir_date(item, kind):
                raise ValueError("invalid_fhir_date")
            walk(item)

    walk(bundle)


def bundle_evidence(bundle):
    entries = bundle_entries(bundle)
    patients = [entry["resource"] for entry in entries if entry["resource"].get("resourceType") == "Patient"]
    if len(patients) != 1:
        raise ValueError("unsupported_fhir_patient_count")
    patient = patients[0]
    fields = evidence(patient)
    for identifier in patient.get("identifier", ()):
        if isinstance(identifier, dict) and isinstance(identifier.get("value"), str):
            token = identity_id(identifier["value"])
            if token:
                fields["MRN"].add(token)
    for name in patient.get("name", ()):
        if isinstance(name, dict):
            if isinstance(name.get("text"), str):
                fields["NAME"].add(name["text"])
            if isinstance(name.get("given"), list) and isinstance(name.get("family"), str):
                fields["NAME"].add(" ".join([*(part for part in name["given"] if isinstance(part, str)), name["family"]]))
    for contact in patient.get("telecom", ()):
        if isinstance(contact, dict) and contact.get("system") in {"phone", "email"} and isinstance(contact.get("value"), str):
            kind = contact["system"].upper()
            fields[kind].update(evidence({kind: contact["value"]})[kind])
    for entry in entries:
        if entry["resource"].get("resourceType") == "Encounter":
            for identifier in entry["resource"].get("identifier", ()):
                if isinstance(identifier, dict) and isinstance(identifier.get("value"), str):
                    if token := identity_id(identifier["value"]):
                        fields["ENCOUNTER"].add(token)
    return fields


OPAQUE_COLUMN = re.compile(r"(?:col(?:umn)?|field|attr(?:ibute)?|var|x)[a-z]?\d+")
NON_PII_TABLE_HEADERS = {
    "drug", "drugname", "medicine", "medication", "brand", "generic", "dose", "dosage",
    "test", "testname", "parameter", "analyte", "unit", "units", "range", "referencerange",
    "ward", "wardname", "department", "dept", "diagnosis", "condition", "icd", "icd10",
    "hospital", "clinic", "facility", "district", "state", "country", "status", "outcome",
    "sex", "gender", "age", "notes", "remarks", "comment", "comments", "chiefcomplaint",
}


def table_evidence_labels(rows):
    """Recover PII semantics in opaque numbered columns and (via hybrid ML) unfamiliar headers."""
    labels = list(rows[0])
    kinds = {resolve_field_kind(label) for label in labels}
    if kinds & {"MRN", "NAME", "DOB", "ENCOUNTER"}:
        candidates = defaultdict(list)
        for pos, label in enumerate(labels):
            normal = field_label(label)
            if normal in EXTRA_PRESERVE_FIELDS or resolve_field_kind(label) or not OPAQUE_COLUMN.fullmatch(normal):
                continue
            values = {ascii_digits(row[pos].strip()) for row in rows[1:] if row[pos].strip()}
            if len(values) < 2:
                continue
            if all(re.fullmatch(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", value) for value in values):
                candidates["EMAIL"].append(pos)
            elif all(re.fullmatch(r"(?:\+91[ -]?)?[6-9]\d{4}[ -]?\d{5}", value) for value in values):
                candidates["PHONE"].append(pos)
        for kind, positions in candidates.items():
            if len(positions) == 1 and kind not in kinds:
                labels[positions[0]] = kind
                kinds.add(kind)

    # Hybrid ML fallback: header-blind Column-Value Classifier for unfamiliar column names
    if ML_FALLBACK_ENABLED and HYBRID_MODELS is not None and HYBRID_MODELS.col_clf is not None and len(rows) >= 3:
        inferred: list[tuple[int, str]] = []
        for pos, label in enumerate(labels):
            normal = field_label(label)
            if (
                normal in EXTRA_PRESERVE_FIELDS
                or normal in DOCTOR_CONTEXTS
                or normal in NON_PII_TABLE_HEADERS
                or resolve_field_kind(label)
                or dynamic_is_age_label(label)
                or dynamic_is_district_label(label)
                or is_date_label(normal)
            ):
                continue
            col_vals = [row[pos].strip() for row in rows[1:] if pos < len(row) and row[pos].strip()]
            pred = HYBRID_MODELS.col_clf.classify_column(col_vals, threshold=ML_COL_THRESHOLD)
            if not pred:
                continue
            # Never duplicate an existing MRN column or misclassify billing/order/sample IDs as MRN
            if pred == "MRN" and (
                "MRN" in kinds
                or any(tok in normal for tok in ("bill", "claim", "invoice", "order", "sample", "receipt", "txn", "voucher"))
            ):
                continue
            inferred.append((pos, pred))
        # Apply ML column labels when there is patient evidence. A high-confidence
        # NAME prediction is itself usable evidence; otherwise an export whose only
        # patient column has a renamed header could leak every name unchanged.
        inferred_kinds = {k for _, k in inferred}
        has_name_prediction = "NAME" in inferred_kinds
        if inferred and (
            kinds & {"MRN", "NAME", "DOB", "ENCOUNTER", "PHONE"}
            or inferred_kinds & {"MRN", "PHONE", "EMAIL"}
            or has_name_prediction
        ):
            label_map = {"NAME": "Patient Name", "ADDRESS": "Address", "PHONE": "Phone", "EMAIL": "Email", "MRN": "MRN"}
            for pos, pred in inferred:
                labels[pos] = label_map[pred]

    # "Years" alone is ambiguous (it can mean duration or tenure), so treat it as
    # age only when the same table has both birth-date and patient-identity evidence
    # and every populated value is a plausible human age. Keep the source header in
    # the emitted CSV; this is only a semantic hint for transformations.
    has_birth_date = any(resolve_field_kind(label) == "DOB" for label in labels)
    has_patient_identity = any(
        resolve_field_kind(label) in {"NAME", "MRN", "ENCOUNTER", "PHONE"}
        for label in labels
    )
    if has_birth_date and has_patient_identity:
        for pos, label in enumerate(labels):
            if field_label(label) not in {"year", "years", "yr", "yrs"}:
                continue
            values = [ascii_digits(row[pos].strip()) for row in rows[1:] if pos < len(row) and row[pos].strip()]
            if values and all(value.isdigit() and 0 <= int(value) <= 125 for value in values):
                labels[pos] = "Age"
    return labels


def record_fields(data, ext, month_first):
    if ext in (".csv", ".tsv") and data:
        labels = table_evidence_labels(data)
        for row in data[1:]:
            if len(row) == len(data[0]):
                yield evidence(dict(zip(labels, row)), month_first)
    elif is_bundle(data):
        yield bundle_evidence(data)
    elif ext == ".json":
        for _, row, name_hint in json_records(data):
            fields = evidence(row)
            if name_hint:
                fields["NAME"].add(name_hint)
            yield fields
    else:
        yield evidence(data, month_first)


def add_record(records, rel, loc, pid, generalized=False):
    records.append({"file": f"sanitized/{rel}", "loc": loc, "patient": pid})
    Stats.generalized += generalized


def safe_json_locator(path):
    parts = []
    for part in path:
        if isinstance(part, str) and sensitive_filename(part):
            part = private_label(part)
        parts.append(str(part).replace("~", "~0").replace("/", "~1"))
    return "".join("/" + part for part in parts) or "doc"


def process_csv(rows, delimiter: str, rel: str, records: list, index, month_first) -> str:
    if not rows:
        return ""
    header = rows[0]
    semantic_header = table_evidence_labels(rows)
    labels = [field_label(column) for column in semantic_header]
    kinds = [resolve_field_kind(column) for column in semantic_header]
    if "MRN" in kinds:
        kinds = ["NAME" if label == "name" and label not in EXTRA_PRESERVE_FIELDS else kind for label, kind in zip(labels, kinds)]
        if "DOB" in kinds:
            kinds = ["ADDRESS" if label == "city" and label not in EXTRA_PRESERVE_FIELDS else kind for label, kind in zip(labels, kinds)]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    w.writerow([private_label(column) if sensitive_filename(column) else column for column in header])
    pid_column = next((i for i, kind in enumerate(kinds) if kind in ("MRN", "NAME", "ENCOUNTER")), None)
    for i, row in enumerate(rows[1:]):
        original = dict(zip(semantic_header, row))
        fields = evidence(original, month_first)
        key = index.resolve(original, fields) if pid_column is not None else None
        pid = pseudonym(key) if key else None
        cleaned = []
        generalized = False
        for cell, kind, label, raw_col in zip(row, kinds, labels, semantic_header):
            if label in EXTRA_PRESERVE_FIELDS:
                safe = cell
            elif kind != "DOB" and is_date_label(label):
                safe = shift_dates(cell, key or f"{rel}#row:{i}", month_first)
                generalized |= safe != cell
            elif dynamic_is_age_label(raw_col):
                safe = band_age(cell, index, key, fields["AREA"])
                generalized |= safe != cell
            else:
                safe = clean_value(cell, kind, context=label, date_key=key or f"{rel}#row:{i}",
                                   index=index, patient_key=key, areas=fields["AREA"])
            cleaned.append(safe)
        if pid:
            cleaned[pid_column] = pid
        w.writerow(cleaned)
        add_record(records, rel, f"row:{i}", pid, generalized)
    return buf.getvalue()


def insert_pseudonym(cleaned, pid):
    """Reuse a string identity field to preserve the input record's shape."""
    def insert(value):
        if isinstance(value, dict):
            for label, child in value.items():
                if child == "[MRN]" or child == "[NAME]":
                    value[label] = pid
                    return True
                if insert(child):
                    return True
        elif isinstance(value, list):
            for child in value:
                if insert(child):
                    return True
        return False

    return insert(cleaned)


def clean_json_record(data, rel, loc, records, index, name_hint=None):
    fields = evidence(data)
    if name_hint:
        fields["NAME"].add(name_hint)
    key = index.resolve(data, fields)
    cleaned = clean_value(
        data,
        context="patients" if fields["MRN"] or fields["NAME"] or loc.startswith("/patients/") else "",
        date_key=key or f"{rel}#{loc}",
        index=index,
        patient_key=key,
        areas=fields["AREA"],
    )
    pid = pseudonym(key) if key and isinstance(cleaned, dict) else None
    if pid and not insert_pseudonym(cleaned, pid):
        pid = None
    add_record(records, rel, loc, pid, has_json_generalization(data))
    return cleaned


def has_json_generalization(data):
    if isinstance(data, list):
        return any(has_json_generalization(item) for item in data)
    if not isinstance(data, dict):
        return False
    for label, value in data.items():
        if is_date_label(field_label(label)) and isinstance(value, str) and DATE_TOKEN.search(value):
            return True
        if dynamic_is_age_label(label) and type(value) in (int, str):
            match = AGE_VALUE.fullmatch(str(value))
            if match and 0 <= int(ascii_digits(match[1])) <= 125 and GENERALIZE_AGES_ENABLED:
                return True
        if has_json_generalization(value):
            return True
    return False


def clean_fhir_value(value, refs, fields, date_key, pid, patient_refs):
    if isinstance(value, list):
        return [clean_fhir_value(item, refs, fields, date_key, pid, patient_refs) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned = {}
    for key, item in value.items():
        label = field_label(key)
        if key in {"data", "url", "hash"} and "contentType" in value:
            continue
        if isinstance(item, str):
            if key in {"reference", "fullUrl"}:
                item = refs.get(item, item)
            elif key == "display" and isinstance(value.get("reference"), str) and value["reference"] in patient_refs:
                item = pid or "[PATIENT]"
            elif is_date_label(label) or key == "timestamp":
                item = shift_dates(item, date_key)
            elif key not in {"id", "resourceType", "system", "code", "url", "status", "unit", "versionId"}:
                item = redact_known(clean_text(item), fields)
        else:
            item = clean_fhir_value(item, refs, fields, date_key, pid, patient_refs)
        cleaned[key] = item
    return cleaned


def process_fhir(bundle, rel, records, index):
    validate_fhir_dates(bundle)
    entries = bundle_entries(bundle)
    fields = bundle_evidence(bundle)
    key = index.resolve(bundle, fields)
    pid = pseudonym(key) if key else None
    refs, patient_refs, new_ids = {}, set(), []
    for entry in entries:
        resource = entry["resource"]
        typ, old = resource.get("resourceType"), resource.get("id")
        if not isinstance(typ, str) or not isinstance(old, str) or not old:
            raise ValueError("invalid_fhir_resource")
        relative = typ + "/" + old
        url = entry.get("fullUrl", relative)
        if not isinstance(url, str) or relative in refs or url in refs:
            raise ValueError("ambiguous_fhir_reference")
        digest = hmac.digest(SECRET, ("fhir|" + url).encode(), "sha256")
        new_id = str(uuid.UUID(bytes=digest[:16], version=4))
        refs[relative] = typ + "/" + new_id
        refs[url] = refs[relative] if url == relative else "urn:uuid:" + new_id
        new_ids.append(new_id)
        if typ == "Patient":
            patient_refs.update((relative, url))
    clean = clean_fhir_value(bundle, refs, fields, key or rel, pid, patient_refs)
    if isinstance(clean.get("id"), str):
        clean["id"] = private_label(clean["id"])
    if isinstance(clean.get("identifier"), dict) and isinstance(clean["identifier"].get("value"), str):
        clean["identifier"]["value"] = private_label(clean["identifier"]["value"])
    if isinstance(clean.get("meta"), dict):
        clean["meta"].pop("source", None)
        if not clean["meta"]:
            del clean["meta"]
    for entry, new_id in zip(bundle_entries(clean), new_ids):
        resource = entry["resource"]
        resource["id"] = new_id
        if resource.get("resourceType") == "Patient":
            for field in ("name", "birthDate", "contact", "telecom", "text", "extension", "identifier",
                          "photo", "communication", "link", "_birthDate", "deceasedDateTime"):
                resource.pop(field, None)
            if pid:
                resource["identifier"] = [{"system": "urn:secret-wards:patient", "value": pid}]
            if isinstance(resource.get("address"), list):
                resource["address"] = [
                    {k: v for k, v in address.items() if k in {"district", "state", "country"}}
                    for address in resource["address"] if isinstance(address, dict)
                ]
                resource["address"] = [address for address in resource["address"] if address]
                if not resource["address"]:
                    del resource["address"]
        elif resource.get("resourceType") == "Encounter":
            resource.pop("identifier", None)
    valid_targets = set()
    for entry in bundle_entries(clean):
        resource = entry["resource"]
        if "id" in resource:
            valid_targets.add(resource["resourceType"] + "/" + resource["id"])
        if "fullUrl" in entry:
            valid_targets.add(entry["fullUrl"])
    pending = [clean]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            ref = item.get("reference")
            if isinstance(ref, str) and (ref.startswith("urn:uuid:") or re.fullmatch(r"[A-Z]\w*/[^/]+", ref)):
                if ref not in valid_targets:
                    raise ValueError("unresolved_fhir_reference")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    add_record(records, rel, "doc", pid, True)
    return clean


def process_json(data, rel: str, records: list, index) -> str:
    if is_bundle(data):
        cleaned = process_fhir(data, rel, records, index)
    else:
        replacements = {}
        for path, row, name_hint in json_records(data):
            loc = safe_json_locator(path)
            replacements[id(row)] = clean_json_record(row, rel, loc, records, index, name_hint)
        cleaned = clean_value(data, records_by_id=replacements)
    return json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n"


def apply_ml_ner(text: str) -> str:
    """Apply trained Linear-Chain CRF line-by-line as a high-precision free-text fallback."""
    if not ML_FALLBACK_ENABLED or HYBRID_MODELS is None or HYBRID_MODELS.ner is None or not text:
        return text
    redact_names = _category_enabled("NAME")
    redact_addresses = _category_enabled("ADDRESS")
    if not redact_names and not redact_addresses:
        return text
    lines = text.splitlines(keepends=True)
    out_lines = []
    for line in lines:
        if not line.strip():
            out_lines.append(line)
            continue
        ending = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
        body = line[:-len(ending)] if ending else line
        cleaned, kinds = HYBRID_MODELS.ner.redact_prose(
            body,
            threshold=ML_NER_THRESHOLD,
            redact_names=redact_names,
            redact_addresses=redact_addresses,
            preserve_doctors=PRESERVE_DOCTORS_ENABLED,
        )
        for kind in kinds:
            Stats.record_entity(kind)
        out_lines.append(cleaned + ending)
    return "".join(out_lines)


def process_text(text: str, rel: str, records: list, index, month_first) -> str:
    fields = evidence(text, month_first)
    key = index.resolve(text, fields)
    pid = pseudonym(key) if key else None
    safe = redact_known(clean_text(text), fields)
    if pid and _category_enabled("MRN"):
        safe = ID_TOKEN.sub(
            lambda match: "[MRN]" if identity_id(match[0]) in index.roots
            or identity_id(match[0]) in index.encounters else match[0],
            safe,
        )
    safe = apply_ml_ner(safe)
    aged = band_note_ages(safe, index, key, fields["AREA"])
    shifted = shift_dates(aged, key or rel, month_first)
    add_record(records, rel, "doc", pid, shifted != safe)
    return f"Patient reference: {pid}\n{shifted}" if pid else shifted


def peak_rss_mb() -> float:
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / 1024 if sys.platform != "darwin" else r / 1048576, 1)
    except Exception:  # noqa: BLE001 - not available on every OS
        return 0.0


def read_document(raw: bytes, ext: str):
    if ext not in (".csv", ".tsv", ".json", ".txt"):
        raise ValueError("unsupported_format")
    if not raw.strip():
        raise ValueError("empty_file")
    text = decode(raw)
    if text is None or re.search(r"[\x00-\x08\x0b\x0e-\x1f]", text):
        raise ValueError("undecodable_text")
    month_first = ext != ".json" and month_first_dates(text)
    delimiter = None
    if ext in (".csv", ".tsv"):
        if re.match(r'\s*(?:\{\s*"|\[\s*\{)', text):
            raise ValueError("mislabeled_table")
        header = text.partition("\n")[0]
        default = "\t" if ext == ".tsv" else ","
        candidates = dict.fromkeys((default, ",", "\t", ";", "|"))
        widths = {sep: len(next(csv.reader([header], delimiter=sep))) for sep in candidates}
        delimiter = max(widths, key=widths.get)
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
        if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows[1:]):
            raise ValueError("ambiguous_table_shape")
        data = rows
    elif ext == ".json":
        data = json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_number)
    else:
        data = text
    return data, month_first, delimiter


FILE_ERRORS = (ValueError, RecursionError, UnicodeError, csv.Error, TypeError, StopIteration, KeyError)
REASONS = {
    "unsupported_format", "empty_file", "undecodable_text", "mislabeled_table",
    "invalid_fhir_entries", "unsupported_fhir_patient_count", "missing_fhir_patient_id",
    "invalid_fhir_patient_reference", "unsupported_fhir_patient_reference",
    "invalid_fhir_date", "duplicate_json_key", "invalid_json_number", "key_collision",
    "ambiguous_table_shape", "unresolved_fhir_reference",
}


def quarantine(entry, exc):
    reason = str(exc) if str(exc) in REASONS else type(exc).__name__
    entry.update(output=None, status="quarantined", reason=reason)


def main() -> int:
    ap = argparse.ArgumentParser(description="Secret Wards offline privacy pipeline")
    ap.add_argument("--input", required=True, help="One file or a directory of files to process recursively")
    ap.add_argument("--output", required=True)
    ap.add_argument("--policy", default=os.environ.get("RAKSHA_POLICY") or str(HERE / "config" / "policy.yaml"))
    a = ap.parse_args()
    t0 = time.monotonic()

    policy_path = Path(a.policy)
    apply_policy(load_policy(policy_path))
    if ML_FALLBACK_ENABLED and HYBRID_MODELS is not None:
        HYBRID_MODELS.load_from(HERE / "models")
    Stats.reset()
    global VOCAB
    VOCAB = ReleaseVocabulary()
    sensitive_label.cache_clear()
    canonical_person_name.cache_clear()

    inp, out = Path(a.input).resolve(), Path(a.output).resolve()
    single_file = inp.is_file()
    if not SECRET or not (single_file or inp.is_dir()) or inp == out or inp in out.parents:
        print("Invalid input, output or missing RAKSHA_SECRET.", file=sys.stderr)
        return 2
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        print("Use an empty output directory.", file=sys.stderr)
        return 2
    # Restrict release artifacts to the current OS account by default. This is
    # defense in depth, not encryption: production deployments still need an
    # encrypted output volume and external key management.
    os.umask(0o077)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        out.chmod(0o700)
    san = out / "sanitized"
    san.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        san.chmod(0o700)
    files, records = [], []
    index = IdentityIndex()
    jobs = []
    cache_budget = 16 * 1024 * 1024
    input_root = inp.parent if single_file else inp
    input_files = [inp] if single_file else sorted(p for p in inp.rglob("*") if p.is_file())
    for path in input_files:
        ext = path.suffix.lower()
        if ext not in (".csv", ".tsv", ".json", ".txt"):
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            files.append({"input_sha256": digest.hexdigest(), "output": None, "status": "quarantined", "reason": "unsupported_format"})
            continue
        raw = path.read_bytes()
        entry = {"input_sha256": hashlib.sha256(raw).hexdigest()}
        files.append(entry)
        try:
            document = read_document(raw, ext)
            for fields in record_fields(document[0], ext, document[1]):
                index.observe(fields)
            cached = document if len(raw) <= cache_budget else None
            if cached is not None:
                cache_budget -= len(raw)
            jobs.append((path, entry, ext, cached))
        except FILE_ERRORS as exc:
            quarantine(entry, exc)
    index.finish()

    for path, entry, ext, cached in jobs:
        local_records = []
        old_identifiers, old_generalized = Stats.identifiers, Stats.generalized
        old_entities = Stats.entities.copy()
        try:
            data, month_first, delimiter = cached if cached is not None else read_document(path.read_bytes(), ext)
            rel = release_path(path.relative_to(input_root))
            if ext in (".csv", ".tsv"):
                result = process_csv(data, delimiter, rel, local_records, index, month_first)
            elif ext == ".json":
                result = process_json(data, rel, local_records, index)
            else:
                result = process_text(data, rel, local_records, index, month_first)
            dest = san / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(result.encode("utf-8"))
            entry.update(output=f"sanitized/{rel}", status="sanitized")
            records.extend(local_records)
        except FILE_ERRORS as exc:
            Stats.identifiers, Stats.generalized = old_identifiers, old_generalized
            Stats.entities = old_entities
            quarantine(entry, exc)

    with open(out / "records.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    n_san = sum(e["status"] == "sanitized" for e in files)
    report = {
        "schema": "raksha-report/1",
        "files": files,
        "counts": {
            "files_total": len(files), "files_sanitized": n_san, "files_quarantined": len(files) - n_san,
            "records_processed": len(records), "identifiers_detected": Stats.identifiers,
            "records_linked": sum(r["patient"] is not None for r in records),
            "records_generalized": Stats.generalized, "records_suppressed": Stats.suppressed,
            "records_quarantined": 0,
        },
        "entities": dict(sorted(Stats.entities.items())),
        "timing": {"seconds": round(time.monotonic() - t0, 2)},
        "resources": {"peak_rss_mb": peak_rss_mb()},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Only counts go to stdout: stdout and stderr are scanned for PII.
    print(f"files {len(files)} sanitized {n_san} quarantined {len(files) - n_san} records {len(records)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OSError:
        print("Could not complete input or output I/O.", file=sys.stderr)
        sys.exit(1)
