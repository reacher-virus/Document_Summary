
import re

import nltk
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lex_rank import LexRankSummarizer
from sumy.nlp.stemmers import Stemmer
from sumy.utils import get_stop_words

LANGUAGE = "english"

_NLTK_READY = False


def ensure_nltk_data(force: bool = False) -> None:
    """
    Make sure the NLTK tokenizer data sumy needs is available, downloading
    it on first use if missing. Safe to call multiple times.
    """
    global _NLTK_READY
    if _NLTK_READY and not force:
        return

    for pkg, path in (("punkt", "tokenizers/punkt"), ("punkt_tab", "tokenizers/punkt_tab")):
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(pkg, quiet=True)

    _NLTK_READY = True


# Roughly how many sentences to pull per summary length setting.
# Scaled against document size in `_sentence_budget`.
LENGTH_RATIOS = {
    "short": 0.08,
    "medium": 0.16,
    "long": 0.28,
}
LENGTH_MIN_SENTENCES = {"short": 3, "medium": 6, "long": 10}
LENGTH_MAX_SENTENCES = {"short": 6, "medium": 12, "long": 20}


class SummarizationError(Exception):
    pass


def _clean_text(text: str) -> str:
    # Collapse excessive whitespace/newlines that PDF extraction can leave behind,
    # while keeping paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _sentence_budget(total_sentences: int, length: str) -> int:
    ratio = LENGTH_RATIOS.get(length, LENGTH_RATIOS["medium"])
    n = max(1, round(total_sentences * ratio))
    n = max(LENGTH_MIN_SENTENCES.get(length, 5), n)
    n = min(LENGTH_MAX_SENTENCES.get(length, 12), n, total_sentences)
    return max(1, n)


def _build_summarizer():
    stemmer = Stemmer(LANGUAGE)
    summarizer = LexRankSummarizer(stemmer)
    summarizer.stop_words = get_stop_words(LANGUAGE)
    return summarizer


def summarize(text: str, length: str = "medium") -> dict:
    """
    Returns:
      {
        "summary": str,              # paragraph-form summary
        "key_points": [str, ...],     # bullet list of key points
        "suggestions": [str, ...],    # improvement suggestions
        "stats": {word_count, sentence_count, summary_word_count}
      }
    """
    if length not in LENGTH_RATIOS:
        length = "medium"

    cleaned = _clean_text(text)
    if len(cleaned.split()) < 20:
        raise SummarizationError(
            "The document is too short to summarize meaningfully "
            "(fewer than 20 words of extracted text)."
        )

    parser = PlaintextParser.from_string(cleaned, Tokenizer(LANGUAGE))
    total_sentences = len(parser.document.sentences)
    if total_sentences == 0:
        raise SummarizationError("No sentences could be parsed from this document.")

    budget = _sentence_budget(total_sentences, length)
    summarizer = _build_summarizer()

    ranked_sentences = summarizer(parser.document, budget)
    summary_sentences = [str(s) for s in ranked_sentences]

    if not summary_sentences:
        raise SummarizationError("Could not generate a summary for this document.")

    # Key points: take the same ranked sentences (already importance-ordered
    # internally by sumy before reassembly), capped independently for bullets.
    key_point_count = min(5, len(summary_sentences))
    key_points = _pick_key_points(cleaned, key_point_count)

    summary_paragraph = " ".join(summary_sentences)

    suggestions = _generate_suggestions(cleaned, total_sentences, summary_sentences)

    stats = {
        "word_count": len(cleaned.split()),
        "sentence_count": total_sentences,
        "summary_word_count": len(summary_paragraph.split()),
    }

    return {
        "summary": summary_paragraph,
        "key_points": key_points,
        "suggestions": suggestions,
        "stats": stats,
    }


def _pick_key_points(cleaned_text: str, count: int) -> list:
    """Independent LexRank pass tuned to surface distinct standalone key points."""
    parser = PlaintextParser.from_string(cleaned_text, Tokenizer(LANGUAGE))
    summarizer = _build_summarizer()
    sentences = summarizer(parser.document, count)
    points = []
    for s in sentences:
        s = str(s).strip()
        if len(s) > 220:
            s = s[:217].rsplit(" ", 1)[0] + "..."
        points.append(s)
    return points


def _generate_suggestions(cleaned_text: str, total_sentences: int, summary_sentences: list) -> list:
    """
    Heuristic, structure-based suggestions about the SOURCE document
    (not the summary) — e.g. length, structure, and clarity signals a
    reader/editor might want to address.
    """
    suggestions = []
    words = cleaned_text.split()
    word_count = len(words)
    paragraphs = [p for p in cleaned_text.split("\n\n") if p.strip()]

    avg_sentence_len = word_count / max(1, total_sentences)
    if avg_sentence_len > 30:
        suggestions.append(
            "Several sentences run quite long (avg. {:.0f} words/sentence). "
            "Breaking these into shorter sentences would improve readability.".format(avg_sentence_len)
        )

    if len(paragraphs) <= 1 and word_count > 300:
        suggestions.append(
            "The document is a single dense block of text. Adding paragraph "
            "breaks or section headings would make it easier to scan."
        )

    if word_count < 150:
        suggestions.append(
            "The document is quite short — consider adding more supporting "
            "detail or examples if this is meant to be a comprehensive reference."
        )

    has_heading_like_lines = any(
        len(line.strip()) < 60 and line.strip().istitle() and line.strip()
        for line in cleaned_text.split("\n")
    )
    if word_count > 500 and not has_heading_like_lines:
        suggestions.append(
            "No clear section headings were detected in a fairly long document. "
            "Adding headings would help readers navigate the content."
        )

    if not re.search(r"\d", cleaned_text):
        suggestions.append(
            "The document contains no numbers, dates, or figures — if this is a "
            "report or analysis, adding concrete data would strengthen it."
        )

    if not suggestions:
        suggestions.append(
            "The document is well-structured overall; no major clarity issues "
            "were detected by automated checks."
        )

    return suggestions[:5]
