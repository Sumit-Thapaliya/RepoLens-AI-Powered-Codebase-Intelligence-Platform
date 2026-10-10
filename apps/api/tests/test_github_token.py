"""GitHub token configuration remains optional, secret, and public-repository-only."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
for source_path in (
    ROOT / "apps" / "api",
    ROOT / "packages" / "shared",
    ROOT / "packages" / "parser",
    ROOT / "packages" / "graph",
):
    sys.path.insert(0, str(source_path))

from app.core.config import Settings
from app.services.github import GITHUB_API_BASE, GitHubClient
from repolens_shared.errors import GitHostError


class GitHubTokenTests(unittest.TestCase):
    def test_token_is_optional_and_blank_values_use_anonymous_access(self) -> None:
        for configured_value in (None, "  "):
            with self.subTest(configured_value=configured_value):
                settings = Settings(_env_file=None, GITHUB_TOKEN=configured_value)
                client = GitHubClient(settings)
                self.assertIsNone(settings.github_token)
                self.assertNotIn("Authorization", client._headers)
                self.assertEqual(
                    settings.public_config()["github"]["rate_limit"],
                    "60 requests/hour (anonymous)",
                )

    def test_configured_token_is_bearer_auth_and_never_in_public_config(self) -> None:
        token = "test-github-token-do-not-log"
        settings = Settings(_env_file=None, GITHUB_TOKEN=token)
        client = GitHubClient(settings)

        self.assertEqual(client._headers["Authorization"], f"Bearer {token}")
        self.assertNotIn(token, repr(settings))
        self.assertNotIn(token, repr(settings.public_config()))
        self.assertEqual(
            settings.public_config()["github"]["rate_limit"],
            "up to 5,000 requests/hour (authenticated)",
        )

    def test_token_does_not_allow_private_repositories(self) -> None:
        token = "test-github-token-do-not-log"
        settings = Settings(_env_file=None, GITHUB_TOKEN=token)
        api_headers = GitHubClient(settings)._headers
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"private": True}, request=request)

        async def check_private_repo_is_rejected() -> None:
            async with httpx.AsyncClient(
                base_url=GITHUB_API_BASE,
                headers=api_headers,
                transport=httpx.MockTransport(handler),
            ) as http_client:
                client = GitHubClient(settings, client=http_client)
                with self.assertRaises(GitHostError):
                    await client.get_repo("owner", "private-repository")

        asyncio.run(check_private_repo_is_rejected())
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].headers["Authorization"], f"Bearer {token}")


if __name__ == "__main__":
    unittest.main()
