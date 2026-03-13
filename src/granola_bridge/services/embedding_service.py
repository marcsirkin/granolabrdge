"""Embedding service using Ollama + ChromaDB for semantic search."""

import logging
from pathlib import Path
from typing import Optional

import httpx

from granola_bridge.config import AppConfig

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Manages embeddings via Ollama and stores them in ChromaDB."""

    def __init__(self, config: AppConfig):
        self.ollama_url = config.embedding.ollama_url.rstrip("/")
        self.model = config.embedding.model
        self.chroma_path = config.get_chroma_path()
        self.auto_start = config.embedding.auto_start
        self._client = None
        self._collection = None
        self._available: Optional[bool] = None
        self._ollama_proc = None  # track subprocess we started

    def _get_collection(self):
        """Lazy-init ChromaDB client and collection."""
        if self._collection is not None:
            return self._collection

        import chromadb

        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.chroma_path))
        self._collection = self._client.get_or_create_collection(
            name="transcript_segments",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"ChromaDB initialized at {self.chroma_path}")
        return self._collection

    async def _try_start_ollama(self) -> bool:
        """Start Ollama if installed. Returns True once Ollama is ready."""
        import shutil
        import subprocess
        import asyncio

        if not shutil.which("ollama"):
            logger.info("Ollama not installed — skipping auto-start")
            return False
        logger.info("Starting Ollama...")
        self._ollama_proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Poll until ready, up to 10s
        for _ in range(20):
            await asyncio.sleep(0.5)
            try:
                async with httpx.AsyncClient(timeout=2) as client:
                    resp = await client.get(f"{self.ollama_url}/api/tags")
                    if resp.status_code == 200:
                        logger.info("Ollama started successfully")
                        return True
            except Exception:
                pass
        logger.warning("Ollama did not become ready in time")
        return False

    async def health_check(self) -> bool:
        """Check if Ollama is running and the embedding model is available."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.ollama_url}/api/tags")
                if resp.status_code != 200:
                    self._available = False
                    return False
                models = resp.json().get("models", [])
                model_names = [m.get("name", "").split(":")[0] for m in models]
                self._available = self.model.split(":")[0] in model_names
                if not self._available:
                    logger.warning(
                        f"Ollama running but model '{self.model}' not found. "
                        f"Available: {model_names}. Run: ollama pull {self.model}"
                    )
                return self._available
        except Exception as e:
            logger.debug(f"Ollama not available: {e}")
            if self.auto_start:
                started = await self._try_start_ollama()
                if started:
                    return await self.health_check()
            self._available = False
            return False

    async def is_available(self) -> bool:
        """Return cached availability or re-check."""
        if self._available is None:
            return await self.health_check()
        return self._available

    async def embed_text(self, text: str) -> list[float]:
        """Get embedding vector for a text string via Ollama."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.ollama_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]

    async def embed_meeting_segments(
        self, meeting_id: str, segments: list[dict]
    ) -> int:
        """Embed and store all segments for a meeting.

        Args:
            meeting_id: The meeting's database ID
            segments: List of segment dicts with text, speaker, source, segment_index, etc.

        Returns:
            Number of segments successfully embedded
        """
        if not segments:
            return 0

        collection = self._get_collection()

        # Remove any existing embeddings for this meeting (for reprocessing)
        try:
            existing = collection.get(where={"meeting_id": meeting_id})
            if existing["ids"]:
                collection.delete(ids=existing["ids"])
        except Exception:
            pass

        ids = []
        documents = []
        metadatas = []

        for seg in segments:
            text = seg.get("text", "").strip()
            if not text:
                continue

            seg_id = f"{meeting_id}_{seg.get('segment_index', 0)}"
            ids.append(seg_id)
            documents.append(text)
            metadatas.append({
                "meeting_id": meeting_id,
                "segment_index": seg.get("segment_index", 0),
                "speaker": seg.get("speaker", ""),
                "source": seg.get("source", ""),
                "start_timestamp": seg.get("start_timestamp", ""),
                "end_timestamp": seg.get("end_timestamp", ""),
            })

        if not ids:
            return 0

        # Embed in batches to avoid overloading Ollama
        batch_size = 20
        embedded_count = 0

        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i : i + batch_size]
            batch_docs = documents[i : i + batch_size]
            batch_meta = metadatas[i : i + batch_size]

            try:
                embeddings = []
                for doc in batch_docs:
                    emb = await self.embed_text(doc)
                    embeddings.append(emb)

                collection.add(
                    ids=batch_ids,
                    documents=batch_docs,
                    embeddings=embeddings,
                    metadatas=batch_meta,
                )
                embedded_count += len(batch_ids)
            except Exception as e:
                logger.error(f"Failed to embed batch {i // batch_size}: {e}")
                # Mark service as potentially unavailable
                self._available = None
                break

        logger.info(f"Embedded {embedded_count}/{len(ids)} segments for meeting {meeting_id}")
        return embedded_count

    def query(
        self,
        query_text: str = "",
        query_embedding: list[float] | None = None,
        n_results: int = 10,
        meeting_id: str | None = None,
    ) -> list[dict]:
        """Query ChromaDB for similar segments.

        Args:
            query_text: Text to search for (used if query_embedding not provided)
            query_embedding: Pre-computed embedding vector
            n_results: Number of results to return
            meeting_id: If set, restrict to segments from this meeting

        Returns:
            List of dicts with id, text, metadata, distance
        """
        collection = self._get_collection()

        where = {"meeting_id": meeting_id} if meeting_id else None

        # Check collection has data
        count = collection.count()
        if count == 0:
            return []

        # Adjust n_results to not exceed available documents
        n_results = min(n_results, count)

        kwargs = {
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where
        if query_embedding:
            kwargs["query_embeddings"] = [query_embedding]
        elif query_text:
            kwargs["query_texts"] = [query_text]
        else:
            return []

        try:
            results = collection.query(**kwargs)
        except Exception as e:
            logger.error(f"ChromaDB query failed: {e}")
            return []

        # Flatten results into list of dicts
        items = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                items.append({
                    "id": doc_id,
                    "text": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0,
                })

        return items

    async def query_async(
        self,
        query_text: str,
        n_results: int = 10,
        meeting_id: str | None = None,
    ) -> list[dict]:
        """Async query: embed the query text then search ChromaDB."""
        try:
            embedding = await self.embed_text(query_text)
            return self.query(
                query_embedding=embedding,
                n_results=n_results,
                meeting_id=meeting_id,
            )
        except Exception as e:
            logger.error(f"Async query failed: {e}")
            return []

    def delete_meeting(self, meeting_id: str) -> None:
        """Delete all embeddings for a meeting."""
        collection = self._get_collection()
        try:
            existing = collection.get(where={"meeting_id": meeting_id})
            if existing["ids"]:
                collection.delete(ids=existing["ids"])
                logger.info(f"Deleted {len(existing['ids'])} embeddings for meeting {meeting_id}")
        except Exception as e:
            logger.error(f"Failed to delete embeddings for meeting {meeting_id}: {e}")
