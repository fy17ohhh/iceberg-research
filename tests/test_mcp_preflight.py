import json

from iceberg_search.mcp import client as mcp_client


def test_github_mcp_is_skipped_without_native_binary_or_docker(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "github": {
                    "command": "docker",
                    "args": ["run", "github-mcp"],
                    "env": {
                        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(mcp_client.shutil, "which", lambda _: None)
    monkeypatch.setattr(mcp_client, "_docker_daemon_available", lambda: False)

    assert mcp_client.create_mcp_clients(str(config_path)) == []


def test_docker_preflight_returns_false_when_cli_is_missing(monkeypatch):
    monkeypatch.setattr(mcp_client.shutil, "which", lambda _: None)

    assert mcp_client._docker_daemon_available() is False


def test_medium_reader_is_skipped_when_ruby_dependency_is_not_ready(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {"medium-reader": {"command": "mcp-medium-reader", "args": []}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_client, "_medium_reader_ready", lambda _: False)

    assert mcp_client.create_mcp_clients(str(config_path)) == []


def test_pdf_reader_mcp_config_connects_without_special_environment(tmp_path, monkeypatch):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "pdf-reader": {
                    "command": "npx",
                    "args": ["-y", "@sylphx/citra"],
                }
            }
        ),
        encoding="utf-8",
    )
    seen_env = {}

    def fake_connect(self):
        seen_env.update(self.server_config.env or {})
        self.tools = []
        return []

    monkeypatch.setattr(mcp_client.MCPClient, "connect", fake_connect)

    clients = mcp_client.create_mcp_clients(str(config_path))

    assert len(clients) == 1
    assert seen_env["PATH"]
