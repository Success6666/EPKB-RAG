import math
import re
from collections import defaultdict


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_+#./-]*|[\u4e00-\u9fff]+", str(text or "").lower()):
        if not token.strip():
            continue
        tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 1:
            tokens.extend(chinese_ngrams(token, 2, 3, 24))
    return list(dict.fromkeys(tokens))


def keyword_score(query_terms: list[str], text: str) -> float:
    text_terms = tokenize(text)
    if not text_terms:
        return 0.0
    frequencies = defaultdict(int)
    for term in text_terms:
        frequencies[term] += 1

    score = 0.0
    length_penalty = math.sqrt(len(text_terms))
    lowered = text.lower()
    for term in query_terms:
        score += frequencies.get(term, 0)
        if term in lowered:
            score += 0.5
    return score / max(length_penalty, 1.0)


def normalize_scores(results) -> dict[str, float]:
    if not results:
        return {}
    scores = [result.score for result in results]
    min_score = min(scores)
    max_score = max(scores)
    if max_score == min_score:
        return {result.chunk_id: 1.0 for result in results}
    return {result.chunk_id: (result.score - min_score) / (max_score - min_score) for result in results}


def chinese_ngrams(text: str, min_n: int, max_n: int, limit: int) -> list[str]:
    grams: list[str] = []
    for size in range(min_n, max_n + 1):
        if len(text) < size:
            continue
        for index in range(0, len(text) - size + 1):
            grams.append(text[index:index + size])
            if len(grams) >= limit:
                return grams
    return grams
