import json

from openai.types.chat import ChatCompletionMessage

from iceberg_search.agents.sonar_models import (
    CoverageGap,
    ReviewResult,
)
from iceberg_search.agents.navigator import Navigator


class FakeContextBuilder:
    def build_context(self, system_prompt, history):
        return [{"role": item.role, "content": item.content} for item in history]


class FakeLLM:
    def __init__(self):
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return ChatCompletionMessage(
            role="assistant",
            content=json.dumps(
                {
                    "analysis": "coverage",
                    "sub_questions": [
                        {
                            "id": "",
                            "label": "Agent 评测",
                            "question": "研究 Agent 的评测指标与 benchmark。",
                            "rationale": "填补评测缺口。",
                        }
                    ],
                }
            ),
        )


def test_navigator_has_separate_plan_and_replan_prompts():
    llm = FakeLLM()
    navigator = Navigator(
        llm=llm,
        context_builder=FakeContextBuilder(),
        max_steps=3,
    )

    initial = navigator.plan("研究 Agent 系统")
    replanned = navigator.replan(
        research_brief="研究 Agent 系统",
        approved_items=[],
        sonar_result=ReviewResult(
            note_reviews=[],
            coverage_gaps=[
                CoverageGap(
                    dimension="评测",
                    reason="缺少可靠性指标",
                    suggested_scope="研究 benchmark 与成功率",
                )
            ],
        ),
    )

    assert initial[0].id.startswith("sq_")
    assert replanned[0].id.startswith("sq_")
    assert llm.calls[0]["tag"] == "navigator:plan"
    assert llm.calls[1]["tag"] == "navigator:replan"
    assert "缺少可靠性指标" in llm.calls[1]["messages"][-1]["content"]
