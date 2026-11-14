"""Fast checks on the pieces a reviewer is most likely to doubt.

Run with:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afs import stats
from afs.agents import Blackboard, CriticAgent
from afs.classify import FailureLabeller, is_failure_record
from afs.common import PROC_DIR, TAB_DIR, read_csv, read_json, read_jsonl
from afs.taxonomy import Taxonomy


class TestTaxonomy(unittest.TestCase):
    def setUp(self):
        self.t = Taxonomy()

    def test_five_dimensions_present(self):
        for dim in ["A_failure_type", "B_cause_class", "C_lifecycle_stage",
                    "D_severity", "E_detection_point"]:
            self.assertIn(dim, self.t.spec["dimensions"])

    def test_primary_dimension_is_single_label(self):
        self.assertFalse(self.t.spec["dimensions"]["A_failure_type"]["multi_label"])

    def test_every_category_has_definition(self):
        for code in self.t.codes("A_failure_type"):
            self.assertTrue(self.t.definition("A_failure_type", code).strip(),
                            f"{code} has no definition")

    def test_required_supervisor_categories_exist(self):
        labels = " ".join(self.t.label("A_failure_type", c).lower()
                          for c in self.t.codes("A_failure_type"))
        for required in ["functionality", "tool", "compatib", "communication",
                         "data structure"]:
            self.assertIn(required, labels)


class TestLabeller(unittest.TestCase):
    def setUp(self):
        self.lab = FailureLabeller()

    def test_deterministic(self):
        text = "TypeError: got an unexpected keyword argument 'max_iter'"
        a = self.lab.label(text)
        b = self.lab.label(text)
        self.assertEqual(a.failure_type, b.failure_type)
        self.assertEqual(a.type_confidence, b.type_confidence)

    def test_tool_precedence_over_parsing(self):
        text = ("[BUG] tool_calls arguments fail validation\n"
                "ValidationError when the agent calls the search tool")
        out = self.lab.label(text)
        self.assertEqual(out.failure_type, "A2_tool_integration")

    def test_compatibility_signal(self):
        text = ("After upgrading to 0.9.0: TypeError: __init__() got an "
                "unexpected keyword argument 'memory'")
        self.assertEqual(self.lab.label(text).failure_type, "A3_compatibility")

    def test_communication_needs_two_agents(self):
        text = ("Multi-agent crew: the manager never hands off to the research "
                "agent, and the group chat loops until maximum turns")
        self.assertEqual(self.lab.label(text).failure_type, "A4_communication")

    def test_short_text_is_unknown_not_forced(self):
        out = self.lab.label("help")
        self.assertEqual(out.failure_type, "A10_unknown")

    def test_proposal_is_unknown(self):
        out = self.lab.label("Proposal: add a new tracing backend for the crew runner")
        self.assertEqual(out.failure_type, "A10_unknown")

    def test_labels_are_valid_codes(self):
        t = Taxonomy()
        for text in ["NameError: name 'Config' is not defined",
                     "No module named 'shopify'",
                     "context window exceeded, history lost",
                     "rate limit 429 from provider"]:
            out = self.lab.label(text)
            self.assertIn(out.failure_type, t.codes("A_failure_type"))
            self.assertIn(out.cause_class, t.codes("B_cause_class"))
            self.assertIn(out.severity, t.codes("D_severity"))

    def test_failure_filter_excludes_feature_request(self):
        keep, reason = is_failure_record(
            "Add streaming support",
            "The current version fails for long inputs. Please add streaming.",
            ["enhancement", "feature request"])
        self.assertFalse(keep)
        self.assertEqual(reason, "feature_request")

    def test_failure_filter_excludes_empty_request(self):
        keep, reason = is_failure_record("Add streaming support", "please add it",
                                         ["enhancement", "feature request"])
        self.assertFalse(keep)
        self.assertIn(reason, {"feature_request", "no_failure_signal"})

    def test_failure_filter_keeps_traceback(self):
        keep, _ = is_failure_record("crash", "Traceback (most recent call last): ...", [])
        self.assertTrue(keep)


class TestStatistics(unittest.TestCase):
    def test_wilson_bounds(self):
        lo, hi = stats.wilson_ci(0, 10)
        self.assertGreaterEqual(lo, 0.0)
        self.assertLess(hi, 0.35)
        lo2, hi2 = stats.wilson_ci(10, 10)
        self.assertLessEqual(hi2, 1.0)
        self.assertGreater(lo2, 0.65)

    def test_kappa_perfect(self):
        k = stats.cohen_kappa(["a", "b", "c"], ["a", "b", "c"])
        self.assertAlmostEqual(k["kappa"], 1.0, places=6)

    def test_kappa_chance_level(self):
        a = ["a", "b"] * 50
        b = ["a"] * 50 + ["b"] * 50
        k = stats.cohen_kappa(a, b)
        self.assertLess(k["kappa"], 0.2)

    def test_macro_f1_perfect(self):
        m = stats.macro_f1(["a", "b"], ["a", "b"])
        self.assertAlmostEqual(m["macro_f1"], 1.0)

    def test_cramers_v_range(self):
        v = stats.cramers_v([[10, 20], [20, 10]])
        self.assertGreaterEqual(v, 0.0)
        self.assertLessEqual(v, 1.0)

    def test_bh_correction_monotone(self):
        out = stats.bh_fdr({"a": 0.001, "b": 0.02, "c": 0.5})
        crit = [out[k]["bh_critical"] for k in ("a", "b", "c")]
        self.assertEqual(crit, sorted(crit))


class TestCritic(unittest.TestCase):
    """The critic must actually reject a wrong number, not just log."""

    def _bb(self):
        recs = [
            {"record_id": "1", "framework": "A", "A_failure_type": "A1_functionality",
             "A_confidence": 0.9, "B_cause_class": "B1_framework_defect",
             "B_evidence_grade": "demonstrated", "D_severity": "D1_blocking",
             "E_detection_point": "E1_framework_runtime",
             "C_lifecycle_stage": "C4_inference"},
            {"record_id": "2", "framework": "B", "A_failure_type": "A1_functionality",
             "A_confidence": 0.9, "B_cause_class": "B1_framework_defect",
             "B_evidence_grade": "supported", "D_severity": "D3_degraded",
             "E_detection_point": "E3_human_observation",
             "C_lifecycle_stage": "C4_inference"},
        ]
        return Blackboard(recs, {"questions": []})

    def test_accepts_correct_metric(self):
        bb = self._bb()
        bb.results["RQ1"] = {"metrics": {"n_records": 2, "top_category": "A1_functionality",
                                         "top_share": 1.0, "n_categories": 1},
                             "table": [{"count": 2}], "note": ""}
        critic = CriticAgent().attach(bb)
        self.assertEqual(critic.verify({"rq": "RQ1"})["decision"], "accept")

    def test_rejects_tampered_metric(self):
        bb = self._bb()
        bb.results["RQ1"] = {"metrics": {"n_records": 2, "top_category": "A1_functionality",
                                         "top_share": 0.5, "n_categories": 1},
                             "table": [{"count": 2}], "note": ""}
        critic = CriticAgent().attach(bb)
        self.assertEqual(critic.verify({"rq": "RQ1"})["decision"], "revise")

    def test_rejects_causal_language_on_association(self):
        bb = self._bb()
        bb.results["RQ3"] = {"metrics": {"n_records": 2, "demonstrated_causes": 1},
                             "table": [], "note": "X causes Y"}
        critic = CriticAgent().attach(bb)
        verdict = critic.verify({"rq": "RQ3"})
        self.assertEqual(verdict["decision"], "revise")


class TestDataset(unittest.TestCase):
    def test_dataset_exists_and_is_well_formed(self):
        path = PROC_DIR / "failures.jsonl"
        if not path.exists():
            self.skipTest("dataset not built yet")
        rows = read_jsonl(path)
        self.assertGreater(len(rows), 300, "expected hundreds of records")
        required = {"record_id", "framework", "A_failure_type", "B_cause_class",
                    "C_lifecycle_stage", "D_severity", "E_detection_point"}
        for r in rows[:200]:
            self.assertTrue(required <= set(r), f"missing keys in {r.get('record_id')}")
        ids = [r["record_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)), "duplicate record ids")


class TestConformance(unittest.TestCase):
    """The artefacts that answer the two briefs must stay internally honest.

    These tests read the generated tables, not the source, so a silent change to
    the pipeline that breaks coverage or drops a requirement fails the suite
    rather than quietly shrinking the claim.
    """

    def test_every_category_has_a_cited_exemplar(self):
        path = TAB_DIR / "taxonomy_exemplars.csv"
        if not path.exists():
            self.skipTest("run `afs validate` first")
        rows = read_csv(path)
        cats = {r["category"] for r in rows}
        t = Taxonomy()
        self.assertEqual(cats, set(t.codes("A_failure_type")))
        for r in rows:
            self.assertTrue(r["url"].startswith("http"), f"{r['record_id']} has no URL")
            self.assertTrue(r["evidence"].strip(), f"{r['record_id']} has no span")

    def test_exemplar_text_reproduces_its_label(self):
        """The record the exemplar cites must still label to the category."""
        path = TAB_DIR / "taxonomy_exemplars.csv"
        texts_p = PROC_DIR / "texts.jsonl"
        if not path.exists() or not texts_p.exists():
            self.skipTest("run `afs validate` first")
        texts = {r["record_id"]: r["text"] for r in read_jsonl(texts_p)}
        lab = FailureLabeller()
        for r in read_csv(path):
            text = texts.get(r["record_id"])
            if not text:
                continue
            self.assertEqual(lab.label(text).failure_type, r["category"],
                             f"declared label does not reproduce for {r['record_id']}")

    def test_findings_validation_reports_all_four_tests(self):
        path = TAB_DIR / "findings_validation.json"
        if not path.exists():
            self.skipTest("run `afs validate` first")
        d = read_json(path)
        for key in ("F1_resampling", "F2_temporal", "F3_leave_one_out",
                    "F4_label_noise"):
            self.assertIn(key, d)
            self.assertIn("verdict", d[key], f"{key} has no verdict")
        s = d["summary"]
        self.assertGreaterEqual(s["claims_tested"], 4)
        self.assertEqual(s["stable"] + s["direction_stable"] + s["not_stable"],
                         s["claims_tested"], "verdict tally does not add up")

    def test_requirements_matrix_covers_both_briefs_and_is_closed(self):
        path = TAB_DIR / "requirements_traceability.csv"
        if not path.exists():
            self.skipTest("run `afs requirements` first")
        rows = read_csv(path)
        self.assertEqual(len(rows), 26)
        self.assertEqual({r["source"] for r in rows},
                         {"supervisor_checklist", "requirements_document"})
        allowed = {"Met", "Met with stated limit"}
        for r in rows:
            self.assertIn(r["status"], allowed, f"{r['id']} is not closed")
            self.assertTrue(r["evidence"].strip(), f"{r['id']} has no evidence")
            self.assertTrue(r["location"].strip(), f"{r['id']} has no location")

    def test_complexity_definition_names_its_limits(self):
        from afs.complexity import definition
        d = definition()
        self.assertEqual(d["construct"], "declared architectural complexity of the "
                                         "failing system")
        self.assertIn("NOT instrumented", d["status"])
        self.assertIn("verbosity", " ".join(d["known_limitations"]))
        self.assertEqual(sorted(d["scale"]), ["0", "1", "2", "3"])

    def test_complexity_tiers_are_bounded(self):
        from afs.complexity import enrich

        path = PROC_DIR / "failures.jsonl"
        if not path.exists():
            self.skipTest("dataset not built yet")
        rows = enrich(read_jsonl(path)[:200])
        tiers = [r["complexity_tier"] for r in rows]
        self.assertTrue(all(t in (0, 1, 2, 3) for t in tiers), "tier outside 0..3")


class TestCodebookCompleteness(unittest.TestCase):
    """A code without a boundary is a coder decision waiting to be invented."""

    def setUp(self):
        self.t = Taxonomy()

    def test_every_code_has_definition_include_exclude(self):
        for dim in self.t.spec["dimensions"]:
            for code in self.t.codes(dim):
                body = self.t.categories(dim)[code]
                self.assertIsInstance(body, dict, f"{code} is a bare label")
                for field in ("label", "definition", "include", "exclude"):
                    self.assertTrue(body.get(field), f"{code} has no {field}")
                    if isinstance(body[field], list):
                        self.assertGreaterEqual(len(body[field]), 1,
                                                f"{code} {field} is empty")

    def test_validate_rejects_bare_label(self):
        import copy

        broken = copy.deepcopy(self.t.spec)
        broken["dimensions"]["C_lifecycle_stage"]["categories"]["C1_setup"] = \
            "Installation, dependency resolution, environment or credentials"
        from afs.taxonomy import Taxonomy as T2

        t2 = T2.__new__(T2)
        t2.spec = broken
        with self.assertRaises(ValueError):
            t2.validate()

    def test_validate_rejects_missing_exclusion(self):
        import copy

        broken = copy.deepcopy(self.t.spec)
        del broken["dimensions"]["E_detection_point"]["categories"]["E2_external_test"]["exclude"]
        from afs.taxonomy import Taxonomy as T2

        t2 = T2.__new__(T2)
        t2.spec = broken
        with self.assertRaises(ValueError):
            t2.validate()

    def test_severity_is_ordered(self):
        sev = self.t.categories("D_severity")
        ranks = [sev[c]["ordinal"] for c in self.t.codes("D_severity")]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(len(set(ranks)), len(ranks))


class TestHuggingFacePackage(unittest.TestCase):
    """The published package must agree with the corpus it claims to describe."""

    def setUp(self):
        self.dir = Path(__file__).resolve().parents[1] / "outputs" / "hf_dataset"
        if not (self.dir / "data" / "train-00000-of-00001.parquet").exists():
            self.skipTest("build the package with `python -m afs.cli hf`")
        try:
            import pyarrow.parquet  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            # Some managed Windows machines block the pyarrow DLL through an
            # Application Control policy. That is an environment constraint, not a
            # defect in the package, and it must not be reported as a test failure:
            # a red suite that means "the host is locked down" trains people to
            # ignore red suites.
            self.skipTest(f"pyarrow unavailable on this host: {exc}")

    def test_parquet_matches_corpus(self):
        import pyarrow.parquet as pq

        from afs.hf_export import FIELDS

        table = pq.read_table(self.dir / "data" / "train-00000-of-00001.parquet")
        corpus = read_jsonl(PROC_DIR / "failures.jsonl")
        self.assertEqual(table.num_rows, len(corpus))
        self.assertEqual(table.column_names, [n for n, _, _ in FIELDS])

    def test_no_full_text_is_redistributed(self):
        import pyarrow.parquet as pq

        table = pq.read_table(self.dir / "data" / "train-00000-of-00001.parquet")
        for col in table.column_names:
            self.assertNotIn(col, ("text", "body", "body_text"),
                             "full report text must not ship in the dataset")
        longest = max(len(t or "") for t in table.column("evidence_span").to_pylist())
        self.assertLess(longest, 1200, "evidence spans must stay short quotations")

    def test_card_front_matter_and_counts_agree(self):
        import pyarrow.parquet as pq
        import yaml

        text = (self.dir / "README.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"), "card needs YAML front matter")
        front = yaml.safe_load(text.split("---\n", 2)[1])
        self.assertIn("configs", front)
        self.assertEqual(front["license"], "cc-by-4.0")
        table = pq.read_table(self.dir / "data" / "train-00000-of-00001.parquet")
        # the row count must be stated in the card, or the docs and data diverge
        self.assertIn(f"{table.num_rows:,}", text)
        # one source of truth for the file list: a dict dataset_info alongside
        # configs makes the Hub's viewer fail to resolve the config
        self.assertNotIn("dataset_info", front)
        # naming the file must match the config glob, or the Hub shows nothing
        self.assertIn("train-*.parquet",
                      front["configs"][0]["data_files"][0]["path"])

    def test_all_labels_are_codes_in_the_shipped_codebook(self):
        import pyarrow.parquet as pq
        import yaml

        shipped = yaml.safe_load(
            (self.dir / "codebook" / "taxonomy.v1.yaml").read_text(encoding="utf-8"))
        codes = {c for dim in shipped["dimensions"]
                 for c in shipped["dimensions"][dim]["categories"]}
        table = pq.read_table(self.dir / "data" / "train-00000-of-00001.parquet")
        for col in ("failure_type", "cause_class", "lifecycle_stage", "severity",
                    "detection_point"):
            unknown = {v for v in table.column(col).to_pylist() if v not in codes}
            self.assertFalse(unknown, f"{col} has codes outside the codebook: {unknown}")

    def test_no_credential_shaped_strings_ship(self):
        import re

        import pyarrow.parquet as pq

        pat = re.compile(r"sk-[A-Za-z0-9_-]{20,}|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"
                         r"|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16}"
                         r"|xox[baprs]-[A-Za-z0-9-]{10,}")
        for name in ("train-00000-of-00001.parquet", "exemplars.parquet"):
            table = pq.read_table(self.dir / "data" / name)
            for col in table.column_names:
                for v in table.column(col).to_pylist():
                    if isinstance(v, str):
                        self.assertIsNone(pat.search(v),
                                          f"{name}:{col} leaks a credential")

    def test_exemplars_cover_every_failure_type(self):
        import pyarrow.parquet as pq

        p = self.dir / "data" / "exemplars.parquet"
        table = pq.read_table(p)
        self.assertEqual(len({c for c in table.column("category").to_pylist()}), 10)


class TestProjectIdentity(unittest.TestCase):
    """The submission cites permanent links, so they must be internally consistent.

    These tests fail when a namespace is half-moved: the case that matters is not
    a dead link, it is one document naming the new owner and another naming the old
    one. That is the failure this class exists to catch.
    """

    def test_derived_urls_agree_with_the_namespace(self):
        from afs import identity as I

        self.assertIn(I.GH_OWNER, I.GH_URL)
        self.assertIn(I.GH_REPO, I.GH_URL)
        self.assertTrue(I.GH_PAGES_URL.startswith(f"https://{I.GH_OWNER}.github.io/"))
        self.assertTrue(I.HF_URL.endswith(I.HF_REPO_ID))
        self.assertTrue(I.HF_REPO_ID.startswith(I.HF_OWNER + "/"))
        self.assertTrue(I.REPORT_URL.startswith(I.SITE_URL))

    def test_no_person_is_named_in_a_namespace_after_a_move(self):
        from afs import identity as I

        if I.GH_OWNER == I.LEGACY_GH_OWNER and I.HF_OWNER == I.LEGACY_HF_OWNER:
            self.skipTest("project has not moved; legacy names are still current")
        for link in I.all_links().values():
            self.assertNotIn(I.LEGACY_GH_OWNER, link)
            self.assertNotIn(I.LEGACY_HF_OWNER, link)

    def test_moved_project_still_records_where_it_came_from(self):
        from afs import identity as I

        if I.HF_OWNER == I.LEGACY_HF_OWNER:
            self.skipTest("project has not moved")
        prior = I.prior_locations()
        self.assertTrue(any(I.LEGACY_HF_REPO in u for u in prior),
                        "a moved release must still credit its original location")

    def test_generated_artefacts_carry_no_stale_namespace(self):
        import subprocess

        root = Path(__file__).resolve().parents[1]
        out = subprocess.run([sys.executable, str(root / "tools" / "check_identity.py")],
                             cwd=root, capture_output=True, text=True,
                             env={**__import__("os").environ,
                                  "PYTHONPATH": str(root / "src")})
        self.assertEqual(out.returncode, 0,
                         f"stale identifiers in shipped artefacts:\n"
                         f"{out.stdout[-2000:]}{out.stderr[-800:]}")

    def test_citation_file_points_at_a_live_dataset_namespace(self):
        from afs import identity as I

        text = (Path(__file__).resolve().parents[1] / "CITATION.cff").read_text(
            encoding="utf-8")
        self.assertIn(I.HF_URL, text,
                      "CITATION.cff must cite the dataset URL from identity.py")
        self.assertIn(I.GH_URL, text)


class TestAuthorshipAndCredit(unittest.TestCase):
    """Authorship appears in six artefacts; it must say the same thing in all of them.

    A changed byline is the easiest thing to update in one place and forget in
    another, and the failure is not cosmetic: a report cover naming one set of
    authors while the citation file names another is the kind of inconsistency a
    supervisor notices first.
    """

    def test_authors_are_unique_and_ordered(self):
        from afs import identity as I

        self.assertGreaterEqual(len(I.AUTHORS), 1)
        names = [(a["given"], a["family"]) for a in I.AUTHORS]
        self.assertEqual(len(names), len(set(names)), "duplicate author")
        for a in I.AUTHORS:
            self.assertTrue(a["given"] and a["family"])

    def test_every_author_has_a_stated_contribution(self):
        from afs import identity as I

        credited = {name for name, _ in I.CONTRIBUTIONS}
        for a in I.AUTHORS:
            self.assertIn(f"{a['given']} {a['family']}", credited,
                          "an author is listed without a credited role")

    def test_rendered_citation_matches_the_author_list(self):
        from afs import identity as I

        text = (Path(__file__).resolve().parents[1] / "CITATION.cff").read_text(
            encoding="utf-8")
        for a in I.AUTHORS:
            self.assertIn(f"family-names: {a['family']}", text)
            self.assertIn(f"given-names: {a['given']}", text)

    def test_report_and_paper_carry_the_same_byline(self):
        from docx import Document

        from afs import identity as I

        reports = Path(__file__).resolve().parents[1] / "outputs" / "reports"
        want = I.author_display(initials=False)
        want_short = I.author_display(initials=True)

        rep = reports / "Agentic_Failure_Study_Report.docx"
        pap = reports / "Agentic_Failure_Study_Paper.docx"
        if not rep.exists() or not pap.exists():
            self.skipTest("build the deliverables first")
        rep_text = "\n".join(p.text for p in Document(rep).paragraphs)
        pap_text = "\n".join(p.text for p in Document(pap).paragraphs)
        self.assertIn(want, rep_text, "report cover byline is stale")
        self.assertIn(want_short, pap_text, "paper byline is stale")
        self.assertIn(I.INSTITUTION, rep_text)

    def test_no_author_placeholder_survives_in_the_paper(self):
        from docx import Document

        pap = (Path(__file__).resolve().parents[1] / "outputs" / "reports"
               / "Agentic_Failure_Study_Paper.docx")
        if not pap.exists():
            self.skipTest("build the paper first")
        text = "\n".join(p.text for p in Document(pap).paragraphs)
        for placeholder in ("[Author name]", "[Supervisor name]", "[Institution]",
                            "[email]"):
            self.assertNotIn(placeholder, text,
                             f"unfilled placeholder in the manuscript: {placeholder}")


class TestSourceAccounting(unittest.TestCase):
    """Every source the brief names must be accounted for, with a reason."""
    def test_each_candidate_source_has_a_verdict_and_reason(self):
        from afs.sources import SOURCES

        self.assertGreaterEqual(len(SOURCES), 5)
        for s in SOURCES:
            self.assertTrue(s["source"].strip())
            self.assertIn(s["used"], {"Yes", "No", "As output"})
            self.assertGreater(len(s["reason"]), 20, s["source"])

    def test_the_sources_the_brief_names_are_present(self):
        from afs.sources import SOURCES

        text = " ".join(s["source"] for s in SOURCES).lower()
        for needle in ("hugging face", "aidev", "crewai", "langgraph", "discord"):
            self.assertIn(needle, text, f"{needle} not accounted for")

    def test_derivation_limit_states_what_is_not_retained(self):
        from afs.sources import DERIVATION_LIMIT

        self.assertIn("not retained", DERIVATION_LIMIT)


class TestAidevCorpus(unittest.TestCase):
    """The second corpus must stay an outcome check, not a relabelled main corpus."""

    def setUp(self):
        from afs import aidev

        self.payload = aidev.load()
        if not (self.payload.get("summary") or {}).get("pull_requests"):
            self.skipTest("AIDev tables not built in this checkout")

    def test_summary_counts_are_internally_consistent(self):
        s = self.payload["summary"]
        self.assertGreater(s["pull_requests"], 100_000)
        self.assertLessEqual(s["merged"], s["pull_requests"])
        self.assertLessEqual(s["fixed_after_review"] + s["abandoned_after_review"],
                             s["review_flagged_human"])

    def test_no_agent_claim_exceeds_its_denominator(self):
        for r in self.payload["per_agent"]:
            self.assertLessEqual(r["merged"], r["pull_requests"])
            self.assertLessEqual(r["closed_unmerged"], r["closed"])
            self.assertGreaterEqual(r["merge_rate_ci_low"], 0.0)
            self.assertLessEqual(r["merge_rate_ci_high"], 1.0)

    def test_construct_note_refuses_the_failure_rate_reading(self):
        note = self.payload["summary"]["construct_note"].lower()
        self.assertIn("upper bound", note)
        self.assertIn("not an estimate", note)

    def test_taxonomy_is_not_claimed_for_this_corpus(self):
        note = self.payload["summary"]["construct_note"].lower()
        self.assertIn("review comment is not a failure report", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
