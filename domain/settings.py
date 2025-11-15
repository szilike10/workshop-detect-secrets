from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

from agent_framework import MCPStdioTool
from agent_framework.openai import OpenAIChatClient


@dataclass
class AppSettings:
    """Central place to load and share application configuration."""

    openai_api_key: str
    openai_model_id: str
    github_token: str
    github_repo: str
    github_owner: str
    target_pr_number: str
    github_toolsets: str
    github_mcp_server_image: str
    secret_detector_agents_count: int
    path_to_docker_exec: str
    chat_client: Optional[OpenAIChatClient] = None
    github_mcp_server: Optional[MCPStdioTool] = None

    @classmethod
    def from_env(cls, dotenv_path: Optional[str] = ".env") -> "AppSettings":
        """
        Load settings from environment variables (optionally from a .env file).

        Passing ``None`` for dotenv_path skips the call to load_dotenv in case
        the caller already handled environment loading upstream.
        """
        if dotenv_path is not None:
            load_dotenv(dotenv_path=dotenv_path)

        def _env_or_default(key: str, default: str) -> str:
            value = os.getenv(key)
            return value if value not in (None, "") else default

        instance = cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model_id=os.getenv("MODEL_ID", ""),
            github_token=os.getenv("GITHUB_PAT_TOKEN", ""),
            github_repo=os.getenv("GITHUB_REPO", ""),
            github_owner=os.getenv("GITHUB_OWNER", ""),
            target_pr_number=os.getenv("TARGET_PR_NUMBER", ""),
            github_toolsets=os.getenv("GITHUB_TOOLSETS", "context,repos,issues,pull_requests,users"),
            github_mcp_server_image=os.getenv(
                "GITHUB_MCP_SERVER_IMAGE", "ghcr.io/github/github-mcp-server"
            ),
            secret_detector_agents_count=int(os.getenv("SECRETS_DETECTOR_AGENT_COUNT", 3)),
            path_to_docker_exec=_env_or_default("DOCKER_EXEC_PATH", "docker"),
        )
        instance.chat_client = OpenAIChatClient(
            api_key=instance.openai_api_key,
            model_id=instance.openai_model_id,
        )
        instance.github_mcp_server = MCPStdioTool(
            name="GitHubMCP",
            command=instance.path_to_docker_exec,
            args=[
                "run",
                "-i",
                "--rm",
                "-e",
                f"GITHUB_PERSONAL_ACCESS_TOKEN={instance.github_token}",
                "-e",
                f"GITHUB_TOOLSETS={instance.github_toolsets}",
                instance.github_mcp_server_image,
            ],
            chat_client=instance.chat_client,
            load_prompts=False
        )
        return instance


def load_settings(dotenv_path: Optional[str] = ".env") -> AppSettings:
    """Helper that wraps ``AppSettings.from_env`` for consistent imports."""
    return AppSettings.from_env(dotenv_path)


# Default settings instance that other modules can import.
settings = load_settings()
