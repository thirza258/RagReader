"""Chunk → character offsets → pages, with the chunkers that ship.

The deployed default is fixed-size chunking with overlap (512/50), whose
chunks are raw slices that can start or end inside whitespace and straddle
page joins; paragraph chunking re-joins stripped paragraphs.
"""
from django.test import SimpleTestCase

from common.chunker import DocumentChunker
from workspace.services.extraction import Extracted, clean_pages
from workspace.services.positions import chunk_positions, locate_chunks

PAGES = [
    "Alpha opens the first page with a sentence about dense embeddings.\nIt wraps onto a second line.",
    "",
    "Beta begins page three and discusses keyword search with BM25 scoring.",
    "Gamma closes the document on page four with notes about reranking passages.",
]


def normalised(text):
    return " ".join(text.split())


class ChunkPositionTests(SimpleTestCase):
    def setUp(self):
        self.clean = clean_pages(Extracted(pages=list(enumerate(PAGES, 1)), paged=True))

    def assert_spans_match(self, chunks, positions):
        for chunk, position in zip(chunks, positions):
            self.assertIsNotNone(position["char_start"], chunk)
            span = self.clean.text[position["char_start"]:position["char_end"]]
            self.assertEqual(normalised(span), normalised(chunk))
            if chunk == chunk.strip():
                self.assertEqual(span, chunk)

    def test_fixed_chunks_with_overlap(self):
        chunks = DocumentChunker(strategy="fixed", chunk_size=50, overlap=10).chunk(self.clean.text)
        positions = chunk_positions(self.clean.text, chunks, self.clean.pages)
        self.assertEqual([p["ordinal"] for p in positions], list(range(len(chunks))))
        self.assert_spans_match(chunks, positions)
        starts = [p["char_start"] for p in positions]
        self.assertEqual(starts, sorted(starts))  # overlapping slices land in order
        self.assertEqual({p["page_start"] for p in positions} | {p["page_end"] for p in positions}, {1, 3, 4})
        straddling = [p for p in positions if p["page_start"] != p["page_end"]]
        self.assertTrue(straddling)
        for position in straddling:
            self.assertLess(position["page_start"], position["page_end"])

    def test_production_sized_fixed_chunks(self):
        chunks = DocumentChunker(strategy="fixed", chunk_size=512, overlap=50).chunk(self.clean.text * 4)
        clean_text = self.clean.text * 4
        positions = chunk_positions(clean_text, chunks, None)
        for chunk, position in zip(chunks, positions):
            span = clean_text[position["char_start"]:position["char_end"]]
            self.assertEqual(normalised(span), normalised(chunk))
            self.assertIsNone(position["page_start"])

    def test_paragraph_chunks(self):
        chunks = DocumentChunker(strategy="paragraph", chunk_size=120, overlap=0).chunk(self.clean.text)
        positions = chunk_positions(self.clean.text, chunks, self.clean.pages)
        self.assert_spans_match(chunks, positions)
        self.assertEqual(positions[0]["page_start"], 1)
        self.assertEqual(positions[-1]["page_end"], 4)

    def test_rejoined_whitespace_still_locates_and_missing_text_is_null(self):
        text = "First sentence here.\n\nSecond sentence follows."
        spans = locate_chunks(text, ["First sentence here. Second sentence follows.", "Not in the text", "  "])
        self.assertEqual(spans[0], (0, len(text)))
        self.assertEqual(spans[1:], [None, None])
