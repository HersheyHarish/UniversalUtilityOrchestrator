from __future__ import annotations

import json
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
from sentence_transformers import SentenceTransformer


EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass
class PolicyChunk:
    """One retrievable policy section stored in the vector index."""

    chunk_id: str
    source: str
    section: str
    text: str

    def to_dict(self, score: float) -> dict[str, Any]:
        snippet = self.text.strip().replace("\n", " ")
        snippet = re.sub(r"\s+", " ", snippet)
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "section": self.section,
            "score": round(float(score), 4),
            "snippet": snippet[:280],
        }


class PolicyRetriever:
    _model: SentenceTransformer | None = None

    def __init__(self, policy_dir: Path, vector_store_dir: Path):
        self.policy_dir = Path(policy_dir)
        self.vector_store_dir = Path(vector_store_dir)
        self.index_path = self.vector_store_dir / "policy_faiss.index"
        self.meta_path = self.vector_store_dir / "policy_metadata.pkl"
        self.version_path = self.vector_store_dir / "policy_versions.json"

    def retrieve(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        """Return the top policy chunks that best match the user query."""
        if top_k <= 0:
            return []

        self._ensure_index()
        if not self.meta_path.exists() or not self.index_path.exists():
            return []

        with self.meta_path.open("rb") as handle:
            metadata = pickle.load(handle)
        chunks: list[PolicyChunk] = metadata["chunks"]
        if not chunks:
            return []

        index = faiss.read_index(str(self.index_path))
        query_embedding = self._model_instance().encode(
            [self._prepare_query(query)],
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype("float32")

        search_k = min(top_k, len(chunks))
        scores, indices = index.search(query_embedding, search_k)

        results: list[dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(chunks):
                continue
            chunk = chunks[idx]
            if chunk.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            results.append(chunk.to_dict(float(score)))
        return results

    def _ensure_index(self) -> None:
        """Create or refresh the FAISS index when policy files have changed."""
        self.vector_store_dir.mkdir(parents=True, exist_ok=True)
        current_versions = self._document_versions()
        cached_versions = self._load_cached_versions()
        if self.index_path.exists() and self.meta_path.exists() and cached_versions == current_versions:
            return
        self._build_index(current_versions)

    def _build_index(self, doc_versions: dict[str, int]) -> None:
        """Chunk policy markdown files, embed them, and persist the index."""
        chunks: list[PolicyChunk] = []
        for path in sorted(self.policy_dir.glob("*.md")):
            chunks.extend(self._chunk_document(path))

        if not chunks:
            dim = self._model_instance().get_sentence_embedding_dimension()
            empty_index = faiss.IndexFlatIP(dim)
            faiss.write_index(empty_index, str(self.index_path))
            with self.meta_path.open("wb") as handle:
                pickle.dump({"chunks": []}, handle)
            self.version_path.write_text(json.dumps(doc_versions, indent=2), encoding="utf-8")
            return

        texts = [self._prepare_document_text(chunk) for chunk in chunks]
        embeddings = self._model_instance().encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype("float32")

        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)
        faiss.write_index(index, str(self.index_path))

        with self.meta_path.open("wb") as handle:
            pickle.dump({"chunks": chunks}, handle)
        self.version_path.write_text(json.dumps(doc_versions, indent=2), encoding="utf-8")

    def _document_versions(self) -> dict[str, int]:
        return {
            path.name: path.stat().st_mtime_ns
            for path in sorted(self.policy_dir.glob("*.md"))
        }

    def _load_cached_versions(self) -> dict[str, int] | None:
        if not self.version_path.exists():
            return None
        try:
            return json.loads(self.version_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _chunk_document(self, path: Path) -> list[PolicyChunk]:
        """Split a markdown file into section-level chunks."""
        raw_text = path.read_text(encoding="utf-8")
        doc_title_match = re.search(r"(?m)^#\s+(.+)$", raw_text)
        doc_title = doc_title_match.group(1).strip() if doc_title_match else path.stem

        section_matches = list(re.finditer(r"(?m)^##\s+(.+)$", raw_text))
        chunks: list[PolicyChunk] = []

        if not section_matches:
            cleaned = self._clean_text(raw_text)
            return [
                PolicyChunk(
                    chunk_id=f"{path.stem}_0",
                    source=path.name,
                    section=doc_title,
                    text=cleaned,
                )
            ]

        for index, match in enumerate(section_matches):
            section_title = match.group(1).strip()
            start = match.end()
            end = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(raw_text)
            cleaned_body = self._clean_text(raw_text[start:end].strip())
            if not cleaned_body:
                continue
            full_text = f"{doc_title}\n{section_title}\n\n{cleaned_body}".strip()
            chunks.append(
                PolicyChunk(
                    chunk_id=f"{path.stem}_{index}",
                    source=path.name,
                    section=section_title,
                    text=full_text,
                )
            )

        return chunks

    @staticmethod
    def _clean_text(text: str) -> str:
        cleaned = re.sub(r"`+", "", text)
        cleaned = re.sub(r"\r\n?", "\n", cleaned)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _prepare_document_text(chunk: PolicyChunk) -> str:
        """Embed chunk text together with source metadata for better matching."""
        return f"Source: {chunk.source}\nSection: {chunk.section}\n{chunk.text}"

    @staticmethod
    def _prepare_query(query: str) -> str:
        return query.strip()

    @classmethod
    def _model_instance(cls) -> SentenceTransformer:
        """Load the shared embedding model only once per Python process."""
        if cls._model is None:
            cls._model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        return cls._model
