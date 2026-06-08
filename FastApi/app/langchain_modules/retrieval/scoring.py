import math
import re
from collections import defaultdict


def tokenize(text: str) -> list[str]:
    raw_tokens: list[str] = []
    ngram_tokens: list[str] = []
    for token in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_+#./-]*|[\u4e00-\u9fff]+", str(text or "").lower()):
        if not token.strip():
            continue
        raw_tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 1:
            ngram_tokens.extend(chinese_ngrams(token, 2, 3, 24))
    return list(dict.fromkeys([*raw_tokens, *ngram_tokens]))


def phrase_search_terms(query: str) -> list[str]:
    candidates: list[str] = []
    for segment in query_phrase_segments(query):
        phrase = strip_query_phrase(segment)
        add_phrase_candidate(candidates, phrase)
    return list(dict.fromkeys(candidates))


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


def query_phrase_segments(query: str) -> list[str]:
    value = str(query or "").lower()
    if not value.strip():
        return []
    separators = r"[\r\n\t,;:!?，。！？；：、（）()\[\]{}<>《》“”‘’\"']+"
    spaced = re.sub(r"\s+", " ", value).strip()
    compact = re.sub(r"\s+", "", value)
    return [segment.strip() for source in (spaced, compact) for segment in re.split(separators, source) if segment.strip()]


def strip_query_phrase(value: str) -> str:
    phrase = re.sub(r"\s+", " ", str(value or "")).strip()
    prefixes = (
        "请帮我",
        "帮我查一下",
        "帮忙查一下",
        "讲一下",
        "讲一讲",
        "讲讲",
        "说一下",
        "说一说",
        "说说",
        "介绍一下",
        "说明一下",
        "请介绍",
        "我想知道",
        "想知道",
        "请问",
        "帮我",
        "帮忙",
        "麻烦",
        "查一下",
        "查询",
        "查找",
        "找一下",
        "检索",
        "搜索",
        "看一下",
        "告诉我",
        "关于",
        "请",
    )
    suffixes = (
        "主要包括哪些",
        "主要包括什么",
        "分别是什么",
        "包括哪些",
        "包括什么",
        "有哪些内容",
        "有哪几项",
        "有哪几条",
        "有哪几个",
        "是什么",
        "是哪些",
        "有哪些",
        "的内容",
        "内容",
        "吗",
        "呢",
        "呀",
    )
    previous = None
    while previous != phrase:
        previous = phrase
        for prefix in prefixes:
            if phrase.startswith(prefix):
                phrase = phrase[len(prefix):].strip()
                break
        for suffix in suffixes:
            if phrase.endswith(suffix):
                phrase = phrase[: -len(suffix)].strip()
                break
    return phrase


def add_phrase_candidate(candidates: list[str], phrase: str) -> None:
    phrase = str(phrase or "").strip(" -_/\\")
    compact = re.sub(r"\s+", "", phrase)
    if len(compact) < 4:
        return
    candidates.append(phrase)
    for piece in re.split(r"\s+", phrase):
        if len(piece) >= 4:
            candidates.append(piece)
    if compact != phrase:
        candidates.append(compact)

    chapter_match = re.match(r"^第[一二三四五六七八九十百千万0-9]+[章节篇部分条款](.{4,})$", compact)
    if chapter_match:
        candidates.append(chapter_match.group(1))
