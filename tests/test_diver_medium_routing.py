import json

from iceberg_search.agents.diver import (
    FETCH_TOOL,
    MEDIUM_READER_TOOL,
    Diver,
)


def _diver_with_medium_tool():
    diver = Diver.__new__(Diver)
    diver.name = "test"
    diver._tool_map = {MEDIUM_READER_TOOL: object()}
    return diver


def test_recognizes_medium_and_custom_publication_urls():
    assert Diver._is_medium_url(
        "https://medium.com/@author/an-article-193459ffc14e"
    )
    assert Diver._is_medium_url(
        "https://towardsdatascience.com/an-article-with-a-slug"
    )
    assert Diver._is_medium_url(
        "https://publication.example.com/an-article-193459ffc14e"
    )
    assert not Diver._is_medium_url("https://example.com/an-article")


def test_routes_medium_fetch_to_dedicated_reader():
    diver = _diver_with_medium_tool()
    url = "https://medium.com/@author/an-article-193459ffc14e"

    name, parameters = diver._route_medium_fetch(
        FETCH_TOOL,
        {"url": url, "max_length": 5000},
    )

    assert name == MEDIUM_READER_TOOL
    assert parameters == {"url": url}


def test_mcp_and_agent_configs_enable_medium_reader():
    with open("configs/mcp_servers.json", encoding="utf-8") as file:
        servers = json.load(file)
    with open("configs/agents.json", encoding="utf-8") as file:
        agents = json.load(file)

    assert servers["medium-reader"] == {
        "command": "mcp-medium-reader",
        "args": [],
    }
    assert MEDIUM_READER_TOOL in agents["diver"]["allowed_tools"]
