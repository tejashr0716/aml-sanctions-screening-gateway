import re
import unicodedata
from typing import Tuple, List, Optional


def normalize_string(s: str) -> str:
    """Normalize string by removing accents, lowercasing, and removing punctuation."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    lowered = no_accents.lower()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return " ".join(cleaned.split())


def compute_soundex_token(token: str) -> str:
    """Compute 4-character American Soundex for a single alphabetic word."""
    token = re.sub(r"[^a-z]", "", token.lower())
    if not token:
        return "0000"

    first_char = token[0].upper()
    mapping = {
        "b": "1", "f": "1", "p": "1", "v": "1",
        "c": "2", "g": "2", "j": "2", "k": "2", "q": "2", "s": "2", "x": "2", "z": "2",
        "d": "3", "t": "3",
        "l": "4",
        "m": "5", "n": "5",
        "r": "6"
    }

    digits = []
    prev_code = mapping.get(token[0], "0")

    for char in token[1:]:
        code = mapping.get(char, "0")
        if code != "0":
            if code != prev_code:
                digits.append(code)
            prev_code = code
        elif char in "aeiouy":
            prev_code = "0"

    soundex_digits = "".join(digits)
    code = (first_char + soundex_digits + "000")[:4]
    return code


def compute_soundex(text: str) -> str:
    """Compute composite soundex code across all tokens in string."""
    tokens = [t for t in normalize_string(text).split() if t]
    if not tokens:
        return "0000"
    codes = [compute_soundex_token(t) for t in tokens]
    return " ".join(codes)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute standard Levenshtein edit distance with two-row DP."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    len1, len2 = len(s1), len(s2)
    current_row = list(range(len2 + 1))

    for i in range(len1):
        previous_row, current_row = current_row, [i + 1] + [0] * len2
        for j in range(len2):
            add = previous_row[j + 1] + 1
            delete = current_row[j] + 1
            change = previous_row[j] + (0 if s1[i] == s2[j] else 1)
            current_row[j + 1] = min(add, delete, change)

    return current_row[len2]


def levenshtein_similarity(s1: str, s2: str) -> float:
    """Compute normalized Levenshtein similarity in range [0.0, 1.0]."""
    if s1 == s2:
        return 1.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    dist = levenshtein_distance(s1, s2)
    return max(0.0, 1.0 - (dist / max_len))


def jaro_similarity(s1: str, s2: str) -> float:
    """Compute Jaro similarity metric."""
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = (max(len1, len2) // 2) - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j]:
                continue
            if s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    transpositions = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    transpositions = transpositions // 2
    return (
        (matches / len1) +
        (matches / len2) +
        ((matches - transpositions) / matches)
    ) / 3.0


def jaro_winkler_similarity(s1: str, s2: str, prefix_scaling: float = 0.1) -> float:
    """Compute Jaro-Winkler similarity metric with prefix bonus."""
    jaro = jaro_similarity(s1, s2)
    if jaro < 0.7:
        return jaro

    prefix_len = 0
    for c1, c2 in zip(s1[:4], s2[:4]):
        if c1 == c2:
            prefix_len += 1
        else:
            break

    return jaro + (prefix_len * prefix_scaling * (1.0 - jaro))


class MultiTierMatcher:
    """Multi-tier sanctions screening engine combining exact, phonetic, and fuzzy heuristics."""

    def __init__(self, default_threshold: float = 0.85):
        self.default_threshold = default_threshold

    def evaluate_normalized(
        self,
        norm_query: str,
        norm_cand: str,
        soundex_query: Optional[str] = None,
        soundex_cand: Optional[str] = None,
        threshold: Optional[float] = None
    ) -> Tuple[bool, float, str, str]:
        thresh = threshold if threshold is not None else self.default_threshold

        if not norm_query or not norm_cand:
            return False, 0.0, "NONE", "NO_INPUT"

        # Tier 1: Exact normalized match
        if norm_query == norm_cand:
            return True, 1.0, "TIER_1_EXACT", "EXACT_NORMALIZED"

        # Check token permutation (e.g. "Smith John" vs "John Smith")
        query_tokens = sorted(norm_query.split())
        cand_tokens = sorted(norm_cand.split())
        if query_tokens == cand_tokens and len(query_tokens) > 1:
            return True, 0.98, "TIER_1_EXACT", "EXACT_TOKEN_PERMUTATION"

        # Quick length prune
        len_q, len_c = len(norm_query), len(norm_cand)
        max_l = max(len_q, len_c)
        min_l = min(len_q, len_c)

        s_q = soundex_query or compute_soundex(norm_query)
        s_c = soundex_cand or compute_soundex(norm_cand)

        # Tier 2: Soundex match
        if s_q == s_c and s_q != "0000":
            jw_score = jaro_winkler_similarity(norm_query, norm_cand)
            if jw_score >= 0.70:
                phonetic_score = max(0.90, jw_score)
                return True, round(phonetic_score, 4), "TIER_2_PHONETIC", "PHONETIC_SOUNDEX"

        # If length difference is too large and soundex doesn't match, prune
        if (max_l - min_l) / max_l > (1.0 - thresh + 0.05):
            return False, 0.0, "NONE", "BELOW_THRESHOLD"

        # Tier 3: Fuzzy metrics (Jaro-Winkler & Levenshtein)
        len_ratio = min_l / max_l
        jw_score = jaro_winkler_similarity(norm_query, norm_cand)

        if len_ratio < 0.6 and abs(len_q - len_c) > 4:
            lev_score = levenshtein_similarity(norm_query, norm_cand)
            max_fuzzy = lev_score
        else:
            if jw_score < thresh - 0.10:
                return False, round(jw_score, 4), "NONE", "BELOW_THRESHOLD"
            lev_score = levenshtein_similarity(norm_query, norm_cand)
            max_fuzzy = max(jw_score, lev_score)

        rule = "FUZZY_JARO_WINKLER" if (max_fuzzy == jw_score and max_fuzzy != lev_score) else "FUZZY_LEVENSHTEIN"

        if max_fuzzy >= thresh:
            return True, round(max_fuzzy, 4), "TIER_3_FUZZY", rule

        return False, round(max_fuzzy, 4), "NONE", "BELOW_THRESHOLD"

    def evaluate_pair(
        self, query: str, candidate: str, threshold: Optional[float] = None
    ) -> Tuple[bool, float, str, str]:
        norm_query = normalize_string(query)
        norm_cand = normalize_string(candidate)
        return self.evaluate_normalized(norm_query, norm_cand, threshold=threshold)
