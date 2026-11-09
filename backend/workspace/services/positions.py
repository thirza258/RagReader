"""Map chunks back to character offsets and pages of the extracted text.

Chunkers do not report offsets, and not every strategy returns verbatim
slices: paragraph chunking strips and re-joins paragraphs, semantic chunking
re-joins sentences with single spaces. So chunks are located in a
whitespace-normalised copy of the text that remembers where each normalised
character came from; the offsets returned point into the original text.
"""


def _normalise(text):
    """(text with every whitespace run collapsed to one space, index map)."""
    chars, origin = [], []
    in_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if not in_space:
                chars.append(" ")
                origin.append(index)
            in_space = True
        else:
            chars.append(char)
            origin.append(index)
            in_space = False
    return "".join(chars), origin


def locate_chunks(text, chunks):
    """[(char_start, char_end) | None] for each chunk, in order.

    Chunks are searched for in document order starting just after the
    previous match, so overlapping and repeated chunks land on successive
    occurrences rather than all on the first.
    """
    normalised, origin = _normalise(text)
    spans, cursor = [], 0
    for chunk in chunks:
        needle = " ".join((chunk or "").split())
        if not needle:
            spans.append(None)
            continue
        found = normalised.find(needle, cursor)
        if found < 0:
            found = normalised.find(needle)
        if found < 0:
            spans.append(None)
            continue
        start = origin[found]
        end = origin[found + len(needle) - 1] + 1
        spans.append((start, end))
        cursor = found + 1
    return spans


def page_at(pages, offset):
    """The page number containing `offset`, or the nearest preceding page."""
    number = None
    for page in pages or []:
        if page["start"] <= offset:
            number = page["number"]
        else:
            break
    return number


def chunk_positions(text, chunks, pages):
    """Position metadata for each chunk: ordinal, char span and page span."""
    positions = []
    for ordinal, span in enumerate(locate_chunks(text, chunks)):
        if span is None:
            positions.append({"ordinal": ordinal, "char_start": None, "char_end": None,
                              "page_start": None, "page_end": None})
            continue
        start, end = span
        positions.append({
            "ordinal": ordinal,
            "char_start": start,
            "char_end": end,
            "page_start": page_at(pages, start) if pages else None,
            "page_end": page_at(pages, end - 1) if pages else None,
        })
    return positions
