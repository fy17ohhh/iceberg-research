import json

from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

from iceberg_research.agents.navigator import Navigator


class FakeLLM:
    def __init__(self, arguments: dict):
        self.arguments = arguments

    def invoke(self, **kwargs):
        return ChatCompletionMessage(
            role="assistant",
            content="",
            tool_calls=[
                ChatCompletionMessageToolCall(
                    id="call_1",
                    type="function",
                    function=Function(
                        name="analyze_query",
                        arguments=json.dumps(self.arguments, ensure_ascii=False),
                    ),
                )
            ],
        )


class LocalJsonLLM:
    disable_tools = True

    def __init__(self, content: str):
        self.content = content
        self.invoke_kwargs = None

    def invoke(self, **kwargs):
        self.invoke_kwargs = kwargs
        return ChatCompletionMessage(role="assistant", content=self.content)


def _navigator(llm):
    return Navigator(llm=llm, context_builder=None, max_steps=3)


def test_navigator_uses_query_aware_fallback_when_model_omits_scope_details():
    navigator = _navigator(FakeLLM({"is_clear": False}))

    result = navigator.analyze("a broad topic")

    assert result.is_clear is False
    assert "a broad topic" in result.message
    assert result.directions == []


def test_navigator_uses_json_mode_for_local_models_without_function_calling():
    llm = LocalJsonLLM(
        "```json\n"
        '{"is_clear": false, "message": "Choose a scope.", '
        '"suggested_directions": ["Architecture", "Evaluation", "Deployment"]}'
        "\n```"
    )

    result = _navigator(llm).analyze("agents overview")

    assert result.is_clear is False
    assert result.message == "Choose a scope."
    assert result.directions == ["Architecture", "Evaluation", "Deployment"]
    assert "tools" not in llm.invoke_kwargs
    assert llm.invoke_kwargs["tag"] == "navigator:intake:json"


def test_navigator_bypasses_llm_for_short_or_acronym_like_queries():
    llm = FakeLLM({"is_clear": True, "research_brief": "should not be used"})

    result = _navigator(llm).analyze("ppo")

    assert result.is_clear is False
    assert "“ppo”" in result.message
    assert result.directions == []
