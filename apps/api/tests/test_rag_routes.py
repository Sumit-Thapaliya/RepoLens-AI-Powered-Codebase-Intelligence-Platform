"""Repository-chat route authorization and unconfigured behavior."""

from __future__ import annotations

import hashlib
import secrets
import sys
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
for source_path in (
    ROOT / "apps" / "api",
    ROOT / "packages" / "shared",
    ROOT / "packages" / "parser",
    ROOT / "packages" / "graph",
):
    sys.path.insert(0, str(source_path))

from app.core import db
from app.models.tables import Analysis, AnalysisWindow, Base, BrowserSession, Repo
from app.main import create_app


class RagChatRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        db.init_db()
        Base.metadata.drop_all(db.get_engine())
        Base.metadata.create_all(db.get_engine())

    def test_chat_is_window_owned_and_gracefully_disabled_without_secrets(self) -> None:
        now = time.time()
        window_id = "rag-chat-window"
        analysis_id = "rag-chat-analysis"
        with TestClient(create_app()) as client:
            token = secrets.token_urlsafe(32)
            session_id = hashlib.sha256(token.encode("utf-8")).hexdigest()
            client.cookies.set("repolens_session", token)

            with db.session_scope() as session:
                repo = Repo(
                    id="rag-chat-repo",
                    owner="owner",
                    name="project",
                    full_name="owner/project",
                    url="https://github.com/owner/project",
                    default_branch="main",
                )
                analysis = Analysis(
                    id=analysis_id,
                    repo_id=repo.id,
                    status="complete",
                    branch="main",
                    commit_sha="a" * 40,
                )
                browser = BrowserSession(
                    id=session_id,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=now + 86_400,
                )
                session.add_all([repo, analysis, browser])
                session.flush()
                owner = AnalysisWindow(
                    analysis_id=analysis_id,
                    session_id=session_id,
                    window_id=window_id,
                    created_at=now,
                    last_seen_at=now,
                )
                session.add(owner)

            headers = {"X-Window-Id": window_id}
            status = client.get(f"/api/analyses/{analysis_id}/chat/status", headers=headers)
            self.assertEqual(status.status_code, 200, status.text)
            self.assertFalse(status.json()["enabled"])
            self.assertFalse(status.json()["indexed"])
            self.assertIn("RAG_DATABASE_URL", status.json()["message"])
            self.assertNotIn("RAG_API_KEY", status.json())

            disabled_chat = client.post(
                f"/api/analyses/{analysis_id}/chat",
                headers=headers,
                json={"question": "Where is authentication enforced?"},
            )
            self.assertEqual(disabled_chat.status_code, 503, disabled_chat.text)

            unauthorized = client.get(
                f"/api/analyses/{analysis_id}/chat/status",
                headers={"X-Window-Id": "another-tab"},
            )
            self.assertEqual(unauthorized.status_code, 404)

            missing_window = client.get(f"/api/analyses/{analysis_id}/chat/status")
            self.assertEqual(missing_window.status_code, 404)


if __name__ == "__main__":
    unittest.main()
