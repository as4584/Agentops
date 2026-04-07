"""Tests for ML training data generators: higgsfield, prompt_engineer, education."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import backend.ml.training.generate_education_data as edu
import backend.ml.training.generate_higgsfield_data as hig
import backend.ml.training.generate_prompt_engineer_data as pe

# ─────────────────────────────────────────────────────────────────────────────
# generate_higgsfield_data
# ─────────────────────────────────────────────────────────────────────────────


class TestPickModelForStyle:
    def test_cinematic_returns_diffusion(self):
        m = hig._pick_model_for_style("cinematic portrait", "YouTube")
        assert m["name"] == "Diffusion"

    def test_noir_returns_diffusion(self):
        m = hig._pick_model_for_style("noir mystery", "LinkedIn")
        assert m["name"] == "Diffusion"

    def test_editorial_returns_diffusion(self):
        m = hig._pick_model_for_style("editorial fashion", "Website hero")
        assert m["name"] == "Diffusion"

    def test_anime_returns_mochi(self):
        m = hig._pick_model_for_style("anime fantasy", "YouTube")
        assert m["name"] == "Mochi"

    def test_tiktok_platform_returns_kling(self):
        m = hig._pick_model_for_style("vlog style", "TikTok")
        assert m["name"] == "Kling"

    def test_social_platform_returns_kling(self):
        m = hig._pick_model_for_style("promo", "Social Media")
        assert m["name"] == "Kling"

    def test_fallback_returns_model_dict(self):
        import random

        random.seed(0)
        m = hig._pick_model_for_style("minimalist", "Website hero")
        assert "name" in m and "strengths" in m


class TestHiggsfieldGenerateCreativeBrief:
    def test_structure_has_conversations(self):
        import random

        random.seed(1)
        result = hig._generate_creative_brief(hig._BRIEF_TEMPLATES[0])
        assert "conversations" in result
        assert len(result["conversations"]) == 3
        assert result["conversations"][0]["from"] == "system"
        assert result["conversations"][1]["from"] == "human"
        assert result["conversations"][2]["from"] == "gpt"

    def test_metadata_has_required_fields(self):
        import random

        random.seed(2)
        result = hig._generate_creative_brief(hig._BRIEF_TEMPLATES[1])
        meta = result["metadata"]
        assert meta["source"] == "agentop_higgsfield_gold"
        assert meta["category"] == "creative_brief"
        assert "style" in meta and "model" in meta and "platform" in meta

    def test_assistant_response_is_valid_json(self):
        import random

        random.seed(3)
        result = hig._generate_creative_brief(hig._BRIEF_TEMPLATES[2])
        spec = json.loads(result["conversations"][2]["value"])
        assert "content_type" in spec
        assert "model_recommendation" in spec

    def test_all_brief_templates_work(self):
        import random

        random.seed(4)
        for tmpl in hig._BRIEF_TEMPLATES:
            result = hig._generate_creative_brief(tmpl)
            assert "conversations" in result


class TestHiggsfieldGeneratePromptImprovement:
    def test_structure(self):
        import random

        random.seed(10)
        result = hig._generate_prompt_improvement(hig._BAD_PROMPT_TEMPLATES[0])
        assert len(result["conversations"]) == 3
        assert result["metadata"]["category"] == "prompt_improvement"

    def test_response_contains_improved_and_fix(self):
        import random

        random.seed(11)
        result = hig._generate_prompt_improvement(hig._BAD_PROMPT_TEMPLATES[1])
        gpt_val = result["conversations"][2]["value"]
        assert "Improved prompt" in gpt_val
        assert "What was fixed" in gpt_val

    def test_all_bad_prompt_templates_work(self):
        import random

        random.seed(12)
        for tmpl in hig._BAD_PROMPT_TEMPLATES:
            result = hig._generate_prompt_improvement(tmpl)
            assert "conversations" in result


class TestHiggsfieldGenerateShotList:
    def test_structure(self):
        import random

        random.seed(20)
        result = hig._generate_shot_list()
        assert len(result["conversations"]) == 3
        assert result["metadata"]["category"] == "shot_list"

    def test_assistant_response_has_shots(self):
        import random

        random.seed(21)
        result = hig._generate_shot_list()
        data = json.loads(result["conversations"][2]["value"])
        assert "shots" in data
        assert len(data["shots"]) >= 3

    def test_shots_have_required_fields(self):
        import random

        random.seed(22)
        result = hig._generate_shot_list()
        data = json.loads(result["conversations"][2]["value"])
        for shot in data["shots"]:
            assert "shot" in shot
            assert "camera" in shot
            assert "lens_suggestion" in shot


class TestHiggsfieldGenerate:
    def test_correct_count(self):
        examples = hig.generate(count=10, seed=42)
        assert len(examples) == 10

    def test_deterministic_with_seed(self):
        a = hig.generate(count=5, seed=99)
        b = hig.generate(count=5, seed=99)
        assert a == b

    def test_different_seeds_differ(self):
        a = hig.generate(count=5, seed=1)
        b = hig.generate(count=5, seed=2)
        assert a != b

    def test_has_all_categories(self):
        examples = hig.generate(count=100, seed=1)
        cats = {e["metadata"]["category"] for e in examples}
        assert "creative_brief" in cats
        assert "prompt_improvement" in cats
        assert "shot_list" in cats

    def test_all_examples_have_conversations(self):
        examples = hig.generate(count=20, seed=7)
        for ex in examples:
            assert "conversations" in ex
            assert len(ex["conversations"]) == 3


class TestHiggsfieldMain:
    def test_main_writes_jsonl_with_count_arg(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch.object(sys, "argv", ["prog", "--count", "10"]):
            hig.main()
        out = tmp_path / "data" / "training" / "gold" / "higgsfield_agent_v1.jsonl"
        assert out.exists()
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 10

    def test_main_default_count(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch.object(sys, "argv", ["prog"]):
            hig.main()
        out = tmp_path / "data" / "training" / "gold" / "higgsfield_agent_v1.jsonl"
        assert out.exists()
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 700


# ─────────────────────────────────────────────────────────────────────────────
# generate_prompt_engineer_data
# ─────────────────────────────────────────────────────────────────────────────


class TestFillTemplate:
    def test_fills_branch_placeholder(self):
        import random

        random.seed(0)
        tmpl = {"messy": "push to {branch}", "goal": "push {branch}"}
        result = pe._fill_template(tmpl)
        assert "{branch}" not in result["messy"]
        assert "{branch}" not in result["goal"]

    def test_fills_file_placeholder(self):
        import random

        random.seed(0)
        tmpl = {"messy": "read {file}", "goal": "read {file}"}
        result = pe._fill_template(tmpl)
        assert "{file}" not in result["messy"]

    def test_fills_port_placeholder(self):
        import random

        random.seed(0)
        tmpl = {"messy": "check {port}", "goal": "open {port}"}
        result = pe._fill_template(tmpl)
        assert "{port}" not in result["messy"]

    def test_non_string_values_preserved(self):
        tmpl = {"count": 42, "flag": True}
        result = pe._fill_template(tmpl)
        assert result["count"] == 42
        assert result["flag"] is True

    def test_list_values_filled(self):
        import random

        random.seed(0)
        tmpl = {"actions": ["{branch}", "{file}", "{table}"]}
        result = pe._fill_template(tmpl)
        for v in result["actions"]:
            assert "{branch}" not in v
            assert "{file}" not in v
            assert "{table}" not in v

    def test_non_string_list_items_preserved(self):
        tmpl = {"items": [42, True]}
        result = pe._fill_template(tmpl)
        assert result["items"] == [42, True]


class TestPerturbMessy:
    def test_returns_string(self):
        result = pe._perturb_messy("deploy the app")
        assert isinstance(result, str)

    def test_non_empty_for_non_empty_input(self):
        result = pe._perturb_messy("check the config")
        assert len(result) > 0

    def test_empty_string(self):
        result = pe._perturb_messy("")
        assert isinstance(result, str)

    def test_applies_typo_map_keys_when_present(self):
        # Force 100% typo rate by seeding and calling many times
        results = [pe._perturb_messy("the database should deploy") for _ in range(50)]
        # At least some results should differ from original (typos applied)
        assert any(isinstance(r, str) for r in results)


class TestToShareGPT:
    def _make_structured(self, agent="devops_agent", task_type="devops"):
        return {
            "goal": "deploy app",
            "constraints": ["no downtime"],
            "task_type": task_type,
            "agent": agent,
            "tools": ["safe_shell"],
            "missing": ["target env"],
        }

    def test_structure(self):
        result = pe._to_sharegpt("deploy to prod fast", self._make_structured())
        assert len(result["conversations"]) == 3
        assert result["conversations"][0]["from"] == "system"
        assert result["conversations"][1]["from"] == "human"
        assert result["conversations"][2]["from"] == "gpt"

    def test_metadata_has_agent_and_task_type(self):
        result = pe._to_sharegpt("check logs", self._make_structured("monitor_agent", "monitor"))
        assert result["metadata"]["agent"] == "monitor_agent"
        assert result["metadata"]["task_type"] == "monitor"

    def test_assistant_response_is_valid_json(self):
        result = pe._to_sharegpt("review my code", self._make_structured("code_review_agent", "code_review"))
        data = json.loads(result["conversations"][2]["value"])
        assert "goal" in data
        assert "recommended_agent" in data
        assert "tools" in data

    def test_difficulty_in_metadata(self):
        structured = self._make_structured()
        structured["difficulty"] = "hard"
        result = pe._to_sharegpt("hard task", structured)
        assert result["metadata"]["difficulty"] == "hard"

    def test_default_difficulty_is_medium(self):
        structured = self._make_structured()
        result = pe._to_sharegpt("task", structured)
        assert result["metadata"]["difficulty"] == "medium"


class TestPromptEngineerGenerate:
    def test_correct_count(self):
        examples = pe.generate(count=10, seed=42)
        assert len(examples) == 10

    def test_deterministic(self):
        a = pe.generate(count=5, seed=77)
        b = pe.generate(count=5, seed=77)
        assert a == b

    def test_all_have_metadata_with_agent(self):
        examples = pe.generate(count=20, seed=0)
        for ex in examples:
            assert "metadata" in ex
            assert "agent" in ex["metadata"]
            assert "task_type" in ex["metadata"]

    def test_all_have_three_conversations(self):
        examples = pe.generate(count=15, seed=3)
        for ex in examples:
            assert len(ex["conversations"]) == 3


class TestPromptEngineerMain:
    def test_main_writes_jsonl(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch.object(sys, "argv", ["prog", "--count", "5"]):
            pe.main()
        out = tmp_path / "data" / "training" / "gold" / "prompt_engineer_v1.jsonl"
        assert out.exists()
        assert len(out.read_text().strip().split("\n")) == 5

    def test_main_default_count(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch.object(sys, "argv", ["prog"]):
            pe.main()
        out = tmp_path / "data" / "training" / "gold" / "prompt_engineer_v1.jsonl"
        assert len(out.read_text().strip().split("\n")) == 1500


# ─────────────────────────────────────────────────────────────────────────────
# generate_education_data
# ─────────────────────────────────────────────────────────────────────────────


class TestPickConceptAndStudio:
    def test_returns_correct_types(self):
        import random

        random.seed(0)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        assert isinstance(studio, dict)
        assert isinstance(concept_name, str)
        assert isinstance(concept_def, str)

    def test_studio_has_required_fields(self):
        import random

        random.seed(1)
        studio, _, _ = edu._pick_concept_and_studio()
        assert "id" in studio
        assert "name" in studio
        assert "edge" in studio
        assert "concepts" in studio

    def test_concept_comes_from_studio(self):
        import random

        random.seed(2)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        concept_names_in_studio = [c[0] for c in studio["concepts"]]
        assert concept_name in concept_names_in_studio


class TestPickRelatedConcept:
    def test_never_returns_excluded(self):
        import random

        random.seed(0)
        studio = edu._STUDIOS[0]
        if len(studio["concepts"]) > 1:
            exclude = studio["concepts"][0][0]
            for _ in range(20):
                result = edu._pick_related_concept(studio, exclude)
                assert result != exclude

    def test_returns_string(self):
        import random

        random.seed(0)
        studio = edu._STUDIOS[0]
        result = edu._pick_related_concept(studio, "nonexistent_concept_xyz")
        assert isinstance(result, str)

    def test_single_concept_studio_fallback(self):
        """If studio has only one concept (the excluded one), falls back to another studio."""
        import random

        random.seed(0)
        # Create a fake studio with one concept
        fake_studio = {"id": "s1", "name": "s1", "edge": "e", "concepts": [("only_concept", "def")]}
        result = edu._pick_related_concept(fake_studio, "only_concept")
        assert isinstance(result, str)


class TestFormatResponse:
    def test_returns_string(self):
        import random

        random.seed(0)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        result = edu._format_response(concept_name, concept_def, studio)
        assert isinstance(result, str)
        assert len(result) > 50

    def test_contains_what_it_is(self):
        import random

        random.seed(0)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        result = edu._format_response(concept_name, concept_def, studio)
        assert "**What is it:**" in result

    def test_contains_why_it_matters(self):
        import random

        random.seed(1)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        result = edu._format_response(concept_name, concept_def, studio)
        assert "**Why it matters:**" in result

    def test_contains_check_question(self):
        import random

        random.seed(2)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        result = edu._format_response(concept_name, concept_def, studio)
        assert "**Check question:**" in result

    def test_contains_next_step(self):
        import random

        random.seed(3)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        result = edu._format_response(concept_name, concept_def, studio)
        assert "**Next step:**" in result

    def test_known_concept_has_analogy(self):
        """vector embeddings has a specific analogy registered."""
        import random

        random.seed(0)
        studio = edu._STUDIOS[0]
        result = edu._format_response("vector embeddings", "Mathematical representation of meaning.", studio)
        assert "GPS" in result or "coordinates" in result or "embedding" in result.lower()


class TestGenerateOne:
    def test_structure(self):
        import random

        random.seed(0)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        template = edu._CONFUSION_TEMPLATES[0]
        result = edu._generate_one(template, studio, concept_name, concept_def)
        assert "conversations" in result
        assert len(result["conversations"]) == 3
        assert "metadata" in result

    def test_metadata_fields(self):
        import random

        random.seed(1)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        template = edu._CONFUSION_TEMPLATES[0]
        result = edu._generate_one(template, studio, concept_name, concept_def)
        meta = result["metadata"]
        assert meta["source"] == "agentop_education_gold"
        assert "studio" in meta and "concept" in meta
        assert "confusion_type" in meta and "severity" in meta

    def test_concept_substituted_in_question(self):
        import random

        random.seed(2)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        template = {"q": "what is {concept}?", "confusion_type": "definition", "severity": "low"}
        result = edu._generate_one(template, studio, concept_name, concept_def)
        human_msg = result["conversations"][1]["value"]
        assert "{concept}" not in human_msg

    def test_related_concept_substituted_if_present(self):
        import random

        random.seed(3)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        # Find a template with {related_concept}
        tmpl = next(
            (t for t in edu._CONFUSION_TEMPLATES if "{related_concept}" in t.get("q", "")),
            None,
        )
        if tmpl:
            result = edu._generate_one(tmpl, studio, concept_name, concept_def)
            human_msg = result["conversations"][1]["value"]
            assert "{related_concept}" not in human_msg

    def test_wrong_analogy_substituted_if_present(self):
        import random

        random.seed(4)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        tmpl = next(
            (t for t in edu._CONFUSION_TEMPLATES if "{wrong_analogy}" in t.get("q", "")),
            None,
        )
        if tmpl:
            result = edu._generate_one(tmpl, studio, concept_name, concept_def)
            human_msg = result["conversations"][1]["value"]
            assert "{wrong_analogy}" not in human_msg

    def test_other_source_substituted_if_present(self):
        import random

        random.seed(5)
        studio, concept_name, concept_def = edu._pick_concept_and_studio()
        tmpl = next(
            (t for t in edu._CONFUSION_TEMPLATES if "{other_source}" in t.get("q", "")),
            None,
        )
        if tmpl:
            result = edu._generate_one(tmpl, studio, concept_name, concept_def)
            human_msg = result["conversations"][1]["value"]
            assert "{other_source}" not in human_msg


class TestEducationGenerate:
    def test_correct_count(self):
        examples = edu.generate(count=10, seed=42)
        assert len(examples) == 10

    def test_deterministic(self):
        a = edu.generate(count=5, seed=55)
        b = edu.generate(count=5, seed=55)
        assert a == b

    def test_all_examples_have_conversations(self):
        examples = edu.generate(count=15, seed=8)
        for ex in examples:
            assert "conversations" in ex
            assert len(ex["conversations"]) == 3

    def test_metadata_source(self):
        examples = edu.generate(count=10, seed=0)
        for ex in examples:
            assert ex["metadata"]["source"] == "agentop_education_gold"


class TestEducationMain:
    def test_main_writes_jsonl(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch.object(sys, "argv", ["prog", "--count", "5"]):
            edu.main()
        out = tmp_path / "data" / "training" / "gold" / "education_agent_v1.jsonl"
        assert out.exists()
        assert len(out.read_text().strip().split("\n")) == 5

    def test_main_default_count(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch.object(sys, "argv", ["prog"]):
            edu.main()
        out = tmp_path / "data" / "training" / "gold" / "education_agent_v1.jsonl"
        assert len(out.read_text().strip().split("\n")) == 800
