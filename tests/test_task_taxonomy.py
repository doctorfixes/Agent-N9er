import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

from shared.task_taxonomy import (
    classify_task,
    compute_value_score,
    get_specialization_boost,
    list_categories,
    TaskCategory,
    ValueTier,
    TASK_DEFINITIONS,
    AGENT_SPECIALIZATIONS,
)


class TestClassifyTask:
    def test_classifies_code_generation(self):
        result = classify_task("Implement a new REST API endpoint for user profiles")
        assert result["category"] == "code_generation"
        assert result["tier"] == "highest_leverage"

    def test_classifies_complex_reasoning(self):
        result = classify_task("Analyze tradeoffs and plan the architecture for scaling")
        assert result["category"] == "complex_reasoning"

    def test_classifies_data_analysis(self):
        result = classify_task("Analyze performance metrics and build a dashboard report")
        assert result["category"] == "data_analysis"

    def test_classifies_research_synthesis(self):
        result = classify_task("Research and summarize findings from recent studies")
        assert result["category"] == "research_synthesis"

    def test_classifies_workflow_automation(self):
        result = classify_task("Automate the ETL pipeline for recurring batch processing")
        assert result["category"] == "workflow_automation"

    def test_classifies_customer_support(self):
        result = classify_task("Build a helpdesk FAQ chatbot for customer support tickets")
        assert result["category"] == "customer_support"

    def test_classifies_content_generation(self):
        result = classify_task("Write a blog article and marketing copy for the launch")
        assert result["category"] == "content_generation"

    def test_classifies_translation(self):
        result = classify_task("Translate the UI strings and localize for multilingual users")
        assert result["category"] == "translation"

    def test_classifies_search_rag(self):
        result = classify_task("Build a RAG retrieval pipeline with vector embeddings")
        assert result["category"] == "search_rag"

    def test_classifies_task_extraction(self):
        result = classify_task("Extract and classify entities from unstructured documents")
        assert result["category"] == "task_extraction"

    def test_classifies_meeting_summarization(self):
        result = classify_task("Summarize the standup meeting and extract action items")
        assert result["category"] == "meeting_summarization"

    def test_classifies_email_triage(self):
        result = classify_task("Triage the email inbox and draft priority replies")
        assert result["category"] == "email_triage"

    def test_classifies_project_planning(self):
        result = classify_task("Create a project plan with sprint roadmap and milestones")
        assert result["category"] == "project_planning"

    def test_classifies_data_cleaning(self):
        result = classify_task("Clean and deduplicate the CSV dataset and validate data")
        assert result["category"] == "data_cleaning"

    def test_classifies_document_comparison(self):
        result = classify_task("Compare the contract changes and audit compliance policy")
        assert result["category"] == "document_comparison"

    def test_classifies_image_generation(self):
        result = classify_task("Generate marketing banner images and brand visuals")
        assert result["category"] == "image_generation"

    def test_classifies_video_scripting(self):
        result = classify_task("Write a video script with storyboard and narration scenes")
        assert result["category"] == "video_scripting"

    def test_classifies_api_documentation(self):
        result = classify_task("Generate OpenAPI documentation for the new endpoints")
        assert result["category"] == "api_documentation"

    def test_classifies_unit_test_generation(self):
        result = classify_task("Generate pytest unit test cases with mock fixtures")
        assert result["category"] == "unit_test_generation"

    def test_classifies_product_mockups(self):
        result = classify_task("Create a wireframe mockup and UI prototype layout")
        assert result["category"] == "product_mockups"

    def test_uncategorized_for_vague_input(self):
        result = classify_task("do something")
        assert result["category"] == "uncategorized"

    def test_empty_objective(self):
        result = classify_task("")
        assert result["category"] == "uncategorized"

    def test_classification_returns_all_fields(self):
        result = classify_task("Implement a function")
        assert "category" in result
        assert "tier" in result
        assert "rank" in result
        assert "label" in result
        assert "leverage_score" in result
        assert "cost_tier" in result
        assert "match_confidence" in result

    def test_inputs_influence_classification(self):
        result = classify_task("Process this", {"type": "code", "language": "python", "implement": True})
        assert result["category"] == "code_generation"


class TestComputeValueScore:
    def test_low_cost_high_leverage(self):
        score = compute_value_score(8.0, "low")
        assert score == round(8.0 / 0.3, 2)

    def test_mid_cost(self):
        score = compute_value_score(5.0, "mid")
        assert score == 5.0

    def test_high_cost(self):
        score = compute_value_score(9.0, "high")
        assert score == 3.0

    def test_unknown_cost_defaults_mid(self):
        score = compute_value_score(4.0, "unknown")
        assert score == 4.0


class TestSpecializationBoost:
    def test_code_specialist_on_code_task(self):
        boost = get_specialization_boost("code_specialist", "code_generation")
        assert boost == 0.15

    def test_code_specialist_on_secondary(self):
        boost = get_specialization_boost("code_specialist", "workflow_automation")
        assert boost == 0.05

    def test_code_specialist_on_unrelated(self):
        boost = get_specialization_boost("code_specialist", "translation")
        assert boost == 0.0

    def test_research_analyst_on_research(self):
        boost = get_specialization_boost("research_analyst", "research_synthesis")
        assert boost == 0.15

    def test_content_creator_on_content(self):
        boost = get_specialization_boost("content_creator", "content_generation")
        assert boost == 0.15

    def test_operations_agent_on_automation(self):
        boost = get_specialization_boost("operations_agent", "workflow_automation")
        assert boost == 0.15

    def test_generalist_no_boost(self):
        boost = get_specialization_boost("generalist", "code_generation")
        assert boost == 0.0

    def test_unknown_profile_no_boost(self):
        boost = get_specialization_boost("nonexistent", "code_generation")
        assert boost == 0.0

    def test_invalid_category_no_boost(self):
        boost = get_specialization_boost("code_specialist", "nonexistent_category")
        assert boost == 0.0


class TestListCategories:
    def test_lists_all_20_categories(self):
        cats = list_categories()
        assert len(cats) == 20

    def test_sorted_by_rank(self):
        cats = list_categories()
        ranks = [c["rank"] for c in cats]
        assert ranks == sorted(ranks)

    def test_filter_by_tier(self):
        highest = list_categories(tier="highest_leverage")
        assert len(highest) == 5
        assert all(c["tier"] == "highest_leverage" for c in highest)

    def test_filter_high_roi(self):
        high_roi = list_categories(tier="high_roi")
        assert len(high_roi) == 5
        assert all(c["tier"] == "high_roi" for c in high_roi)

    def test_filter_operational(self):
        ops = list_categories(tier="operational")
        assert len(ops) == 5
        assert all(c["tier"] == "operational" for c in ops)

    def test_filter_creative_technical(self):
        creative = list_categories(tier="creative_technical")
        assert len(creative) == 5
        assert all(c["tier"] == "creative_technical" for c in creative)

    def test_includes_value_score(self):
        cats = list_categories()
        for c in cats:
            assert "value_score" in c
            assert c["value_score"] > 0

    def test_invalid_tier_returns_empty(self):
        result = list_categories(tier="nonexistent")
        assert result == []


class TestTaskDefinitions:
    def test_all_categories_defined(self):
        expected = set(TaskCategory) - {TaskCategory.UNCATEGORIZED}
        defined = set(TASK_DEFINITIONS.keys()) - {TaskCategory.UNCATEGORIZED}
        assert expected == defined

    def test_ranks_are_unique(self):
        ranks = [d["rank"] for k, d in TASK_DEFINITIONS.items() if k != TaskCategory.UNCATEGORIZED]
        assert len(ranks) == len(set(ranks))

    def test_ranks_are_1_to_20(self):
        ranks = sorted(d["rank"] for k, d in TASK_DEFINITIONS.items() if k != TaskCategory.UNCATEGORIZED)
        assert ranks == list(range(1, 21))

    def test_all_have_keywords(self):
        for cat, defn in TASK_DEFINITIONS.items():
            if cat != TaskCategory.UNCATEGORIZED:
                assert len(defn["keywords"]) > 0

    def test_all_specializations_reference_valid_categories(self):
        valid = set(TaskCategory)
        for name, spec in AGENT_SPECIALIZATIONS.items():
            for cat in spec["primary"] + spec["secondary"]:
                assert cat in valid, f"{name} references invalid category {cat}"
