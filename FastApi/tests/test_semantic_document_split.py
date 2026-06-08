import unittest

from app.langchain_modules.retrieval.document_processor import semantic_child_split_text


class SemanticDocumentSplitTests(unittest.TestCase):
    def test_heading_stays_with_first_body_line(self):
        text = (
            "\u7b2c\u4e00\u7ae0 \u603b\u5219\n"
            "\u672c\u7ae0\u89c4\u5b9a\u9002\u7528\u8303\u56f4\u548c\u57fa\u672c\u539f\u5219\u3002\n"
            "\u7b2c\u4e8c\u6761 \u804c\u8d23\n"
            "\u90e8\u95e8\u8d1f\u8d23\u843d\u5b9e\u5ba1\u6279\u548c\u5f52\u6863\u3002"
        )

        chunks = semantic_child_split_text(text, max_chars=32)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertIn("\u7b2c\u4e00\u7ae0 \u603b\u5219\n\u672c\u7ae0", chunks[0])
        self.assertIn("\u7b2c\u4e8c\u6761 \u804c\u8d23\n\u90e8\u95e8", chunks[1])

    def test_sentence_boundaries_are_preferred(self):
        text = "\u7532\u53e5\u8bf4\u660e\u80cc\u666f\u3002\u4e59\u53e5\u8bf4\u660e\u8981\u6c42\u3002\u4e19\u53e5\u8bf4\u660e\u4f8b\u5916\u60c5\u5f62\u3002"

        chunks = semantic_child_split_text(text, max_chars=15)

        self.assertEqual(
            chunks,
            [
                "\u7532\u53e5\u8bf4\u660e\u80cc\u666f\u3002",
                "\u4e59\u53e5\u8bf4\u660e\u8981\u6c42\u3002",
                "\u4e19\u53e5\u8bf4\u660e\u4f8b\u5916\u60c5\u5f62\u3002",
            ],
        )

    def test_long_unpunctuated_text_falls_back_to_budgeted_chunks(self):
        text = "abcdefghij" * 12

        chunks = semantic_child_split_text(text, max_chars=25, overlap_chars=5)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 25 for chunk in chunks))
        self.assertEqual(chunks[0][-5:], chunks[1][:5])


if __name__ == "__main__":
    unittest.main()
