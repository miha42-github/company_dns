import unittest
from chunker import split_sentences, chunk, phrases

words = lambda s: len(s.split())


class ChunkerTests(unittest.TestCase):
    def test_abbreviations_do_not_split(self):
        t = "Apple Inc. is an American company. It was founded by Steve Jobs in the U.S. in 1976. J. Smith runs it."
        self.assertEqual(len(split_sentences(t)), 3)

    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk("One sentence only.", words, target=128), ["One sentence only."])

    def test_chunks_stay_under_cap_and_cover_everything(self):
        text = " ".join(f"Sentence number {i} talks about thing {i} at some length here." for i in range(40))
        cs = chunk(text, words, target=30, hard_cap=50)
        self.assertGreater(len(cs), 3)
        self.assertTrue(all(words(c) <= 50 for c in cs))
        joined = " ".join(cs)
        for i in range(40):
            self.assertIn(f"Sentence number {i} ", joined)

    def test_one_sentence_overlap(self):
        text = "Aa bb. Cc dd. Ee ff. Gg hh. Ii jj. Kk ll."
        cs = chunk(text, words, target=6, hard_cap=10)
        self.assertEqual(cs[0], "Aa bb. Cc dd. Ee ff.")
        self.assertTrue(cs[1].startswith("Ee ff."))

    def test_overlong_sentence_is_split(self):
        s = ", ".join(f"word{i}" for i in range(100)) + "."
        cs = chunk(s, words, target=20, hard_cap=30)
        self.assertTrue(all(words(c) <= 30 for c in cs))
        self.assertGreater(len(cs), 2)


class PhraseTests(unittest.TestCase):
    HITACHI = ("Hitachi, Ltd. is a major Japanese multinational conglomerate headquartered in Tokyo, specializing in digital solutions, green energy, and sustainable infrastructure. "
               "Founded in 1910 as an electrical repair shop, the company has evolved into a global powerhouse combining information technology (IT) with operational technology (OT) to drive social innovation. "
               "Hitachi operates across several key sectors, including digital services (such as data storage via Hitachi Vantara), power grids and clean energy solutions (Hitachi Energy), advanced railway mobility, and industrial systems. "
               "With a workforce of nearly 290,000 employees globally, the company is highly focused on digital transformation and has committed to achieving carbon neutrality across its operations by 2030.")

    def test_a_marketing_list_becomes_business_phrases(self):
        p = phrases(self.HITACHI)
        for want in ["digital solutions", "green energy", "sustainable infrastructure", "data storage", "power grids",
                     "clean energy solutions", "advanced railway mobility", "industrial systems"]:
            self.assertIn(want, p)
        # headcount, founding and headquarters sentences contribute nothing
        for junk in ["workforce of nearly", "employees globally", "Hitachi operates"]:
            self.assertNotIn(junk, p)

    def test_ampersands_and_digit_tokens(self):
        p = phrases("Its divisions include Fabric & Home Care, and it is ranked 60th on the Forbes Global 2000 list.")
        self.assertIn("Home Care", p)
        self.assertFalse(any("th on" in x or "2000" in x for x in p), p)

    def test_short_or_empty_fragments_are_dropped(self):
        self.assertEqual(phrases("Big. Old."), [])


if __name__ == "__main__":
    unittest.main()
