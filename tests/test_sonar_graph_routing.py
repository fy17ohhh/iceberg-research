from iceberg_research.agents.planning_models import SubQuestion
from iceberg_research.agents.sonar_models import (
    CriterionReview,
    NoteReview,
    ReviewResult,
)
from iceberg_research.graph.graph_builder import build_graph


def _criterion(passed=True, evidence="ok"):
    return CriterionReview(passed=passed, evidence=evidence)


class FakeNavigator:
    def __init__(self):
        self.replan_calls = 0

    def plan(self, research_brief):
        return [
            SubQuestion(
                id="sq_memory",
                label="Memory",
                question="研究 Agent 长期记忆。",
                rationale="核心维度",
            )
        ]

    def replan(self, **kwargs):
        self.replan_calls += 1
        return []


class FakeDiver:
    def __init__(self, name):
        self.name = name

    def run(self, sub_question, note_feedback=None):
        return f"note from {self.name}; feedback={note_feedback}", {}


class RetryThenApproveSonar:
    def __init__(self):
        self.pair_ids = []

    def review(self, research_brief, pending_items, approved_items=None):
        item = pending_items[0]
        self.pair_ids.append(item.pair_id)
        if len(self.pair_ids) == 1:
            return ReviewResult(
                note_reviews=[
                    NoteReview(
                        pair_id=item.pair_id,
                        relevance=_criterion(),
                        depth=_criterion(False, "缺少数据"),
                        citations=_criterion(),
                        sources=_criterion(),
                        completeness=_criterion(),
                        verdict="retry",
                        retry_feedback="补充量化数据",
                    )
                ]
            )
        return ReviewResult(
            note_reviews=[
                NoteReview(
                    pair_id=item.pair_id,
                    relevance=_criterion(),
                    depth=_criterion(),
                    citations=_criterion(),
                    sources=_criterion(),
                    completeness=_criterion(),
                    verdict="approved",
                )
            ]
        )


class FakeSynthesizer:
    def __init__(self):
        self.notes = []

    def run(self, research_brief, notes):
        self.notes = notes
        return "final report"


class FakePipeline:
    def __init__(self):
        self.saved = []

    def add_text(self, text, query):
        self.saved.append((text, query))


def test_retry_keeps_stable_question_id_and_creates_new_attempt_pair_id():
    navigator = FakeNavigator()
    sonar = RetryThenApproveSonar()
    synthesizer = FakeSynthesizer()
    pipeline = FakePipeline()
    graph = build_graph(
        navigator=navigator,
        sonar=sonar,
        create_diver=lambda name: FakeDiver(name),
        synthesizer=synthesizer,
        pipeline=pipeline,
        max_rounds=3,
    )

    result = graph.invoke(
        {"research_brief": "研究 Agent Memory", "session_id": "test"}
    )

    assert result["final_report"] == "final report"
    assert sonar.pair_ids == [
        "sq_memory:attempt:1",
        "sq_memory:attempt:2",
    ]
    assert "补充量化数据" in synthesizer.notes[0]
    assert navigator.replan_calls == 0
