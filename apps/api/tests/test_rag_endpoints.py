"""Integration tests for /api/v1/rag endpoints using TestClient with mocked services."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lex_agents_api.main import create_app
from lex_agents_api.settings import Settings
from lex_agents_rag.assembler import AssembledContext
from lex_agents_rag.query_rewriter import RewrittenQuery
from lex_agents_rag.retriever import RankedChunk
from lex_agents_shared.types import CitationMapping


def _make_ranked_chunk(n: int) -> RankedChunk:
    return RankedChunk(
        chunk_id=f"chunk_{n:04d}",
        score=1.0 / n,
        rank=n,
        metadata={"source_id": "32013R0575", "hierarchy_path": f"CRR > Art. {n}"},
        text=f"Artículo {n}: requisitos de capital del 8%.",
        context_text=f"Contexto del artículo {n}.",
        source_label=f"32013R0575 — Art. {n}",
    )


def _make_assembled_context(n: int = 3) -> AssembledContext:
    mappings = [
        CitationMapping(
            index=i,
            chunk_id=f"chunk_{i:04d}",
            source_id="32013R0575",
            hierarchy_path=f"CRR > Art. {i}",
            fragment_text=f"Artículo {i}: texto.",
        )
        for i in range(1, n + 1)
    ]
    context_text = "\n\n".join(
        f"[REF:{m.index}]\n{m.hierarchy_path}\n{m.fragment_text}" for m in mappings
    )
    return AssembledContext(context_text=context_text, citation_mapping=mappings)


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


@pytest.fixture
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        env="dev",
        anthropic_api_key="sk-ant-test",  # type: ignore[arg-type]
        qdrant_url="http://localhost:6333",
        reranker_enabled=False,
    )
    monkeypatch.setattr("lex_agents_api.routers.rag.get_settings", lambda: settings)
    monkeypatch.setattr("lex_agents_api.settings._settings", settings)


class TestSearchEndpoint:
    @patch("lex_agents_api.routers.rag._get_retriever")
    @patch("lex_agents_api.routers.rag._get_reranker")
    @patch("lex_agents_api.routers.rag._get_query_rewriter")
    def test_search_200(
        self,
        mock_qr: MagicMock,
        mock_ranker: MagicMock,
        mock_retriever: MagicMock,
        client: TestClient,
    ) -> None:
        chunks = [_make_ranked_chunk(i) for i in range(1, 4)]

        mock_qr.return_value.rewrite.return_value = RewrittenQuery(
            original="CRR capital",
            expanded_query="Reglamento (UE) 575/2013 capital",
            added_terms=["Reglamento (UE) 575/2013"],
        )
        mock_retriever.return_value.search.return_value = chunks
        mock_ranker.return_value.rerank.return_value = chunks

        response = client.post(
            "/api/v1/rag/search",
            json={"query": "CRR capital", "top_k": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert data["query_rewritten"] == "Reglamento (UE) 575/2013 capital"
        assert len(data["results"]) == 3


class TestAnswerEndpoint:
    @patch("lex_agents_api.routers.rag._get_retriever")
    @patch("lex_agents_api.routers.rag._get_reranker")
    @patch("lex_agents_api.routers.rag._get_query_rewriter")
    @patch("lex_agents_api.routers.rag.Anthropic")
    def test_answer_200_contains_citations(
        self,
        mock_anthropic_cls: MagicMock,
        mock_qr: MagicMock,
        mock_ranker: MagicMock,
        mock_retriever: MagicMock,
        client: TestClient,
    ) -> None:
        chunks = [_make_ranked_chunk(i) for i in range(1, 4)]
        assembled = _make_assembled_context(3)

        mock_qr.return_value.rewrite.return_value = RewrittenQuery(
            original="requisitos CET1",
            expanded_query="capital de nivel 1 ordinario CET1",
            added_terms=["capital de nivel 1 ordinario"],
        )
        mock_retriever.return_value.search.return_value = chunks
        mock_ranker.return_value.rerank.return_value = chunks

        # Mock Anthropic LLM response
        llm_content = MagicMock()
        llm_content.text = "Según [REF:1] el requisito CET1 es del 4,5%."
        llm_response = MagicMock()
        llm_response.content = [llm_content]
        mock_anthropic_cls.return_value.messages.create.return_value = llm_response

        with patch("lex_agents_api.routers.rag.ContextAssembler") as mock_asm:
            mock_asm.return_value.assemble.return_value = assembled
            response = client.post(
                "/api/v1/rag/answer",
                json={"query": "requisitos CET1"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "citations" in data
        assert len(data["citations"]) == 3
        assert data["citations"][0]["index"] == 1

    @patch("lex_agents_api.routers.rag._get_retriever")
    @patch("lex_agents_api.routers.rag._get_reranker")
    @patch("lex_agents_api.routers.rag._get_query_rewriter")
    @patch("lex_agents_api.routers.rag.Anthropic")
    def test_answer_includes_verification_status_pending(
        self,
        mock_anthropic_cls: MagicMock,
        mock_qr: MagicMock,
        mock_ranker: MagicMock,
        mock_retriever: MagicMock,
        client: TestClient,
    ) -> None:
        mock_qr.return_value.rewrite.return_value = RewrittenQuery(
            original="consulta",
            expanded_query="consulta",
            added_terms=[],
        )
        mock_retriever.return_value.search.return_value = []
        mock_ranker.return_value.rerank.return_value = []

        llm_content = MagicMock()
        llm_content.text = "No dispongo de fundamento normativo para esta consulta."
        llm_response = MagicMock()
        llm_response.content = [llm_content]
        mock_anthropic_cls.return_value.messages.create.return_value = llm_response

        with patch("lex_agents_api.routers.rag.ContextAssembler") as mock_asm:
            mock_asm.return_value.assemble.return_value = AssembledContext(
                context_text="", citation_mapping=[]
            )
            response = client.post(
                "/api/v1/rag/answer",
                json={"query": "consulta"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "pending"
