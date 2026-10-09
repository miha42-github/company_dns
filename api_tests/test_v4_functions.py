"""L4: V4-only functions: global search (keyword, semantic, hybrid), the tokeniser check, Industry Match (match and map).

These assert structure and ranges, not search quality: whether the codes are *right* is what the evaluation in
`experiments/company-sic-eval/` measures. SQL and profiles are in test_limits_and_profiles.py (they need a server with known credentials).
"""
from urllib.parse import quote

from common import ServerTestCase, get, post

SYSTEMS = ["US SIC", "ISIC", "EU NACE", "Japan SIC"]


class GlobalSearch(ServerTestCase):
    def test_keyword_search_spans_every_system_and_tags_each_hit(self):
        status, body, _ = get("/V4.0/global/sic/description/manufactur")
        self.assertEqual(status, 200)
        self.assertEqual(sorted({h["source_type"] for h in body["data"]}), sorted(SYSTEMS))
        for hit in body["data"][:20]:
            self.assertTrue({"source_type", "section_id", "class_id", "class_desc"} <= set(hit))

    def test_semantic_search_ranks_from_one_and_descends(self):
        for path in ("/V4.0/na/sic/similarity/", "/V4.0/global/sic/similarity/"):
            with self.subTest(path=path):
                _, body, _ = get(path + quote("software for banks") + "?k=5")
                hits = body["data"]
                self.assertEqual([h["rank"] for h in hits], [1, 2, 3, 4, 5])
                sims = [h["similarity"] for h in hits]
                self.assertEqual(sims, sorted(sims, reverse=True))
                self.assertTrue(all(0 <= s <= 1 for s in sims))
        _, body, _ = get("/V4.0/global/sic/similarity/" + quote("software for banks") + "?k=20")
        self.assertGreater(len({h["source_type"] for h in body["data"]}), 1, "a global search draws on more than one system")

    def test_hybrid_search_fuses_keyword_and_semantic(self):
        _, body, _ = get("/V4.0/global/sic/hybrid/" + quote("oil and gas") + "?k=5")
        hits = body["data"]
        self.assertEqual([h["rank"] for h in hits], [1, 2, 3, 4, 5])
        scores = [h["rrf_score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for h in hits:
            self.assertTrue(set(h["engines"]) <= {"keyword", "semantic"} and h["engines"])
            self.assertTrue({"source_type", "keyword_rank", "semantic_rank", "similarity"} <= set(h))

    def test_the_tokeniser_check_reports_truncation(self):
        _, short, _ = get("/V4.0/na/sic/similarity-check?q=software")
        self.assertEqual(short["data"]["truncated"], False)
        self.assertEqual(short["data"]["max_tokens"], 256)
        _, long_, _ = get("/V4.0/na/sic/similarity-check?q=" + quote("word " * 400))
        self.assertTrue(long_["data"]["truncated"])
        self.assertGreater(long_["data"]["actual_tokens"], long_["data"]["max_tokens"])


class IndustryMatch(ServerTestCase):
    TEXT = ("We design and manufacture industrial robots and also provide cloud software and financial services to banks and insurers.")

    def match(self, **body):
        status, resp, _ = post("/V4.0/global/sic/match", body)
        self.assertEqual(status, 200, resp)
        return resp["data"]

    def test_a_recommended_set_of_two_to_five_per_system_with_evidence(self):
        data = self.match(text=self.TEXT, systems=SYSTEMS)
        self.assertEqual(sorted(s["system"] for s in data["systems"]), sorted(SYSTEMS))
        for system in data["systems"]:
            with self.subTest(system=system["system"]):
                self.assertTrue(2 <= len(system["recommended"]) <= 5)
                for rec in system["recommended"]:
                    self.assertTrue({"code", "title", "similarity", "votes", "hierarchy", "unique_key"} <= set(rec))
                    self.assertTrue(rec["hierarchy"])
                    self.assertTrue("evidence_chunk" in rec and "evidence_phrase" in rec)

    def test_the_default_is_us_sic_only(self):
        data = self.match(text=self.TEXT)
        self.assertEqual([s["system"] for s in data["systems"]], ["US SIC"])

    def test_the_response_shows_how_the_text_was_read_and_states_its_limits(self):
        data = self.match(text=self.TEXT)
        self.assertTrue({"tokens", "chunks", "chunk_target_tokens", "phrases"} <= set(data["input"]))
        codes = {l["code"] for l in data["limitations"]}
        self.assertTrue({"suggestion_not_a_decision", "english_only"} <= codes, codes)

    def test_a_long_description_is_split_into_chunks(self):
        long_text = " ".join([self.TEXT] * 15)
        data = self.match(text=long_text)
        self.assertGreater(len(data["chunks"]), 1)
        self.assertGreater(data["input"]["tokens"], 256)
        self.assertTrue(data["input"]["truncated_without_chunking"], "the model alone would have cut this text off")

    def test_rematching_the_segments_a_user_kept(self):
        data = self.match(chunks=["We make industrial robots.", "We provide cloud software to banks."])
        self.assertEqual(len(data["chunks"]), 2)
        self.assertTrue(data["systems"][0]["recommended"])

    def test_a_very_short_input_is_flagged(self):
        codes = {l["code"] for l in self.match(text="shoes")["limitations"]}
        self.assertIn("short_input", codes)


class Map(ServerTestCase):
    def map(self, **body):
        status, resp, _ = post("/V4.0/global/sic/map", body)
        self.assertEqual(status, 200, resp)
        return resp["data"]

    def test_codes_are_carried_into_the_requested_systems_by_similarity(self):
        data = self.map(**{"from": "US SIC", "codes": ["3571"], "to": ["ISIC", "EU NACE"]})
        self.assertEqual(data["from"], "US SIC")
        self.assertEqual(data["used_description"], False)
        self.assertEqual(sorted(t["system"] for t in data["targets"]), ["EU NACE", "ISIC"])
        for target in data["targets"]:
            self.assertTrue(target["recommended"])
            self.assertLessEqual(len(target["recommended"]), 5)
            for rec in target["recommended"]:
                self.assertTrue({"code", "title", "similarity", "from_codes", "basis", "hierarchy"} <= set(rec))
                self.assertIn("3571", rec["from_codes"])

    def test_a_description_ranks_the_candidates(self):
        data = self.map(**{"from": "US SIC", "codes": ["3571"], "to": ["ISIC"], "description": "Designs and sells personal computers."})
        self.assertTrue(data["used_description"])

    def test_the_default_is_every_other_system(self):
        data = self.map(**{"from": "ISIC", "codes": ["2620"]})
        self.assertEqual(sorted(t["system"] for t in data["targets"]), sorted(s for s in SYSTEMS if s != "ISIC"))

    def test_the_answer_says_it_is_by_similarity_and_a_suggestion(self):
        data = self.map(**{"from": "US SIC", "codes": ["3571"], "to": ["ISIC"]})
        self.assertTrue({l["code"] for l in data["limitations"]} >= {"by_similarity", "suggestion_not_a_decision"})


if __name__ == "__main__":
    import unittest
    unittest.main()
