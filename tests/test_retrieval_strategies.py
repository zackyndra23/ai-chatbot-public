"""Tests for sd_retrieval_strategies.py.

Run (stdlib only, no pytest):
    python tests/test_retrieval_strategies.py
"""
from __future__ import annotations
import os, sys, unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestResolutionContext(unittest.TestCase):
    def test_dataclass_is_frozen(self):
        from modules.system_detection import sd_retrieval_strategies as srs
        ctx = srs.ResolutionContext(service_id="wbs", tenant_id="default")
        with self.assertRaises(FrozenInstanceError):
            ctx.service_id = "other"  # frozen → mutation blocked

    def test_all_fields_default_none(self):
        from modules.system_detection import sd_retrieval_strategies as srs
        ctx = srs.ResolutionContext()
        self.assertIsNone(ctx.service_id)
        self.assertIsNone(ctx.tenant_id)
        self.assertIsNone(ctx.channel_id)
        self.assertIsNone(ctx.user_segment)
        self.assertIsNone(ctx.time_of_day_utc_hour)


class TestResolvers(unittest.TestCase):
    def test_resolve_mmr_lambda_returns_cfg_default_regardless_of_ctx(self):
        from modules.system_detection import sd_retrieval_strategies as srs
        fake_cfg = SimpleNamespace(REDUNDANCY_MMR_LAMBDA=0.55)
        with patch.object(srs, "cfg", fake_cfg):
            v1 = srs._resolve_mmr_lambda(srs.ResolutionContext())
            v2 = srs._resolve_mmr_lambda(srs.ResolutionContext(service_id="wbs", tenant_id="abc"))
        self.assertAlmostEqual(v1, 0.55)
        self.assertAlmostEqual(v2, 0.55)

    def test_resolve_fuzzy_threshold_returns_cfg_default(self):
        from modules.system_detection import sd_retrieval_strategies as srs
        fake_cfg = SimpleNamespace(REDUNDANCY_FUZZY_THRESHOLD=0.81)
        with patch.object(srs, "cfg", fake_cfg):
            v = srs._resolve_fuzzy_threshold(srs.ResolutionContext(channel_id="crisp"))
        self.assertAlmostEqual(v, 0.81)

    def test_resolve_embedding_threshold_returns_cfg_default(self):
        from modules.system_detection import sd_retrieval_strategies as srs
        fake_cfg = SimpleNamespace(REDUNDANCY_EMBEDDING_THRESHOLD=0.91)
        with patch.object(srs, "cfg", fake_cfg):
            v = srs._resolve_embedding_threshold(srs.ResolutionContext())
        self.assertAlmostEqual(v, 0.91)


class TestMMRStrategy(unittest.TestCase):
    def test_mmr_calls_max_marginal_relevance_search_with_correct_params(self):
        from langchain_core.documents import Document
        from modules.system_detection import sd_retrieval_strategies as srs

        fake_vs = MagicMock()
        fake_docs = [Document(page_content=f"d{i}", metadata={}) for i in range(4)]
        fake_vs.max_marginal_relevance_search.return_value = fake_docs

        fake_cfg = SimpleNamespace(
            REDUNDANCY_MMR_LAMBDA=0.7,
            REDUNDANCY_MMR_FETCH_K_MULTIPLIER=2,
        )
        ctx = srs.ResolutionContext()
        with patch.object(srs, "cfg", fake_cfg):
            out = srs._mmr_strategy(fake_vs, "q", k=4, ctx=ctx)

        # Asserts on the underlying MMR call:
        fake_vs.max_marginal_relevance_search.assert_called_once()
        call_kwargs = fake_vs.max_marginal_relevance_search.call_args.kwargs
        call_args = fake_vs.max_marginal_relevance_search.call_args.args
        # langchain_chroma signature: (query, k=..., fetch_k=..., lambda_mult=...)
        self.assertEqual(call_args[0], "q")
        self.assertEqual(call_kwargs.get("k"), 4)
        self.assertEqual(call_kwargs.get("fetch_k"), 8)  # 4 × multiplier 2
        self.assertAlmostEqual(call_kwargs.get("lambda_mult"), 0.7)
        self.assertEqual(out, fake_docs)

    def test_mmr_returns_empty_on_chroma_exception(self):
        from modules.system_detection import sd_retrieval_strategies as srs
        fake_vs = MagicMock()
        fake_vs.max_marginal_relevance_search.side_effect = RuntimeError("chroma boom")
        fake_cfg = SimpleNamespace(REDUNDANCY_MMR_LAMBDA=0.7, REDUNDANCY_MMR_FETCH_K_MULTIPLIER=2)
        with patch.object(srs, "cfg", fake_cfg):
            out = srs._mmr_strategy(fake_vs, "q", k=4, ctx=srs.ResolutionContext())
        self.assertEqual(out, [])


class TestFuzzyStrategy(unittest.TestCase):
    def test_fuzzy_dedups_textually_similar_chunks(self):
        from langchain_core.documents import Document
        from modules.system_detection import sd_retrieval_strategies as srs

        # Over-fetch 8, return 4 after dedup. Two near-duplicates: a, a'.
        a = Document(page_content="Whistleblowing system is a reporting tool", metadata={})
        a_dup = Document(page_content="Whistleblowing system reporting tool is", metadata={})  # near-dup
        b = Document(page_content="Background screening verifies employee records", metadata={})
        c = Document(page_content="Mystery shopping evaluates customer service", metadata={})
        d = Document(page_content="Audit reveals compliance gaps", metadata={})
        e = Document(page_content="Fraud examination detects irregularities", metadata={})

        fake_vs = MagicMock()
        fake_vs.similarity_search.return_value = [a, a_dup, b, c, d, e]  # 6 returned

        fake_cfg = SimpleNamespace(REDUNDANCY_FUZZY_THRESHOLD=0.85)
        with patch.object(srs, "cfg", fake_cfg):
            out = srs._fuzzy_strategy(fake_vs, "q", k=4, ctx=srs.ResolutionContext())

        # over-fetch is k*2 = 8 but vs returned 6; near-dup a_dup should be filtered
        fake_vs.similarity_search.assert_called_once()
        call_kwargs = fake_vs.similarity_search.call_args.kwargs
        self.assertEqual(call_kwargs.get("k"), 8)
        self.assertLessEqual(len(out), 4)
        contents = [d.page_content for d in out]
        # Either `a` or `a_dup` survives, not both
        a_present = a.page_content in contents
        a_dup_present = a_dup.page_content in contents
        self.assertTrue(a_present != a_dup_present, "exactly one of (a, a_dup) survives dedup")


class TestEmbeddingStrategy(unittest.TestCase):
    def test_embedding_dedups_via_cosine_proxy(self):
        """Embedding strategy uses similarity_search_with_score (distance, lower=closer).
        Two docs with near-identical distance to query AND near-identical to each other
        should have one filtered."""
        from langchain_core.documents import Document
        from modules.system_detection import sd_retrieval_strategies as srs

        # 6 candidates with (doc, distance) tuples returned from Chroma.
        # docs 0 and 1 are near-identical content (cosine proxy via re-embed mock below).
        a = Document(page_content="Whistleblowing reporting tool", metadata={})
        a_dup = Document(page_content="Whistleblowing reporting tool.", metadata={})  # near-identical
        b = Document(page_content="Background screening service", metadata={})
        c = Document(page_content="Mystery shopping evaluation", metadata={})
        d = Document(page_content="Audit compliance gaps", metadata={})
        e = Document(page_content="Fraud examination tool", metadata={})

        fake_vs = MagicMock()
        fake_vs.similarity_search_with_score.return_value = [
            (a, 0.10), (a_dup, 0.11), (b, 0.30), (c, 0.40), (d, 0.45), (e, 0.50),
        ]

        # Embedding strategy uses the embedding function on doc texts for the cosine.
        fake_embed = MagicMock()
        # Make a and a_dup have nearly identical vectors → cosine ~= 1.0
        fake_embed.embed_documents.side_effect = lambda texts: [
            [1.0, 0.0, 0.0] if "Whistleblowing" in t else
            [0.0, 1.0, 0.0] if "Background" in t else
            [0.0, 0.0, 1.0] if "Mystery" in t else
            [0.5, 0.5, 0.0] if "Audit" in t else
            [0.0, 0.5, 0.5]
            for t in texts
        ]
        fake_vs._embedding_function = fake_embed

        fake_cfg = SimpleNamespace(REDUNDANCY_EMBEDDING_THRESHOLD=0.92)
        with patch.object(srs, "cfg", fake_cfg):
            out = srs._embedding_strategy(fake_vs, "q", k=4, ctx=srs.ResolutionContext())

        # over-fetch k*2 = 8 but vs returns 6
        call_kwargs = fake_vs.similarity_search_with_score.call_args.kwargs
        self.assertEqual(call_kwargs.get("k"), 8)
        # near-duplicate filtered out
        contents = [d.page_content for d in out]
        self.assertLessEqual(len(out), 4)
        a_present = a.page_content in contents
        a_dup_present = a_dup.page_content in contents
        self.assertTrue(a_present != a_dup_present)


class TestDispatcher(unittest.TestCase):
    def test_dispatcher_returns_none_for_normal(self):
        """The strict-additive contract: method=normal MUST return None
        and MUST NOT touch any vectorstore / Mongo."""
        from modules.system_detection import sd_retrieval_strategies as srs

        # If the dispatcher invoked the vectorstore for `normal`, the test would
        # raise from the MagicMock's .similarity_search side_effect.
        fake_vs = MagicMock()
        fake_vs.similarity_search.side_effect = AssertionError("normal must not call Chroma")
        fake_vs.max_marginal_relevance_search.side_effect = AssertionError("normal must not call Chroma")
        fake_vs.similarity_search_with_score.side_effect = AssertionError("normal must not call Chroma")

        result = srs.retrieve_with_strategy(
            "normal", "q", scope="unbiased", k=4, vectorstore=fake_vs
        )
        self.assertIsNone(result)

    def test_dispatcher_dispatches_mmr(self):
        from langchain_core.documents import Document
        from modules.system_detection import sd_retrieval_strategies as srs
        fake_docs = [Document(page_content="d", metadata={})]
        fake_vs = MagicMock()
        fake_vs.max_marginal_relevance_search.return_value = fake_docs
        fake_cfg = SimpleNamespace(REDUNDANCY_MMR_LAMBDA=0.7, REDUNDANCY_MMR_FETCH_K_MULTIPLIER=2)
        with patch.object(srs, "cfg", fake_cfg):
            out = srs.retrieve_with_strategy(
                "mmr", "q", scope="service_biased", k=4, vectorstore=fake_vs,
                ctx=srs.ResolutionContext(service_id="wbs"),
            )
        self.assertEqual(out, fake_docs)

    def test_dispatcher_unknown_method_returns_none(self):
        """Unknown method shouldn't crash — return None for graceful fallback."""
        from modules.system_detection import sd_retrieval_strategies as srs
        out = srs.retrieve_with_strategy(
            "garbage_method_name", "q", scope="unbiased", k=4, vectorstore=MagicMock()
        )
        self.assertIsNone(out)

    def test_dispatcher_method_is_case_insensitive(self):
        from modules.system_detection import sd_retrieval_strategies as srs
        out = srs.retrieve_with_strategy("NORMAL", "q", scope="unbiased", k=4, vectorstore=MagicMock())
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
