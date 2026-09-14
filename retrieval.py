"""
retrieval.py — Lightweight code search index.

Uses TF-IDF + cosine similarity.

For normal code-specific questions, relevant chunks are ranked
using TF-IDF similarity.

For broad questions such as:
    - Explain the architecture
    - How can this code be improved?
    - What does this project do?

the index also returns the best available chunks even when
the question has no exact lexical match.
"""

from dataclasses import dataclass
from typing import List

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from parser import Chunk


@dataclass
class SearchResult:
    chunk: Chunk
    score: float


class CodeIndex:

    upgrade_note = (
        "To upgrade to neural embeddings later: replace TfidfVectorizer "
        "with sentence-transformers or OpenAI embeddings while keeping "
        "the Chunk objects and ranking structure."
    )

    def __init__(self, chunks: List[Chunk]):
        self.chunks = chunks
        self._matrix = None
        self._vectorizer = None
        self._fit()

    def _doc_text(self, chunk: Chunk) -> str:

        return (
            f"{chunk.name} "
            f"{chunk.name} "
            f"{chunk.docstring} "
            f"{chunk.file_path} "
            f"{chunk.source}"
        )

    def _fit(self):

        if not self.chunks:
            return

        docs = [
            self._doc_text(chunk)
            for chunk in self.chunks
        ]

        self._vectorizer = TfidfVectorizer(
            max_features=20000,
            token_pattern=r"(?u)\b\w[\w_]+\b",
            ngram_range=(1, 2),
            stop_words="english",
        )

        self._matrix = self._vectorizer.fit_transform(docs)

    def query(
        self,
        text: str,
        top_k: int = 6
    ) -> List[SearchResult]:

        if not self.chunks:
            return []

        # ----------------------------------------------------
        # If TF-IDF is not available, return first chunks.
        # ----------------------------------------------------

        if self._vectorizer is None:
            return [
                SearchResult(
                    chunk=chunk,
                    score=0.0
                )
                for chunk in self.chunks[:top_k]
            ]

        # ----------------------------------------------------
        # Convert question to TF-IDF vector.
        # ----------------------------------------------------

        q_vec = self._vectorizer.transform(
            [text]
        )

        sims = cosine_similarity(
            q_vec,
            self._matrix
        ).flatten()

        ranked_idx = sims.argsort()[::-1]

        results = []

        # ----------------------------------------------------
        # Normal case:
        # return chunks with actual similarity.
        # ----------------------------------------------------

        for index in ranked_idx:

            if sims[index] > 0:

                results.append(
                    SearchResult(
                        chunk=self.chunks[index],
                        score=float(sims[index])
                    )
                )

            if len(results) >= top_k:
                break

        # ----------------------------------------------------
        # IMPORTANT FALLBACK
        #
        # Broad questions may have no lexical overlap with
        # source code.
        #
        # Example:
        # "Explain the architecture"
        #
        # There may be no word "architecture" in the code.
        #
        # Instead of returning [], give the LLM some code
        # context so it can reason about the repository.
        # ----------------------------------------------------

        if not results:

            fallback_chunks = self._fallback_chunks(
                top_k
            )

            return [
                SearchResult(
                    chunk=chunk,
                    score=0.0
                )
                for chunk in fallback_chunks
            ]

        # ----------------------------------------------------
        # If we found only a few results, supplement them
        # with a few useful repository chunks.
        # ----------------------------------------------------

        if len(results) < top_k:

            existing_ids = {
                result.chunk.id
                for result in results
            }

            fallback_chunks = self._fallback_chunks(
                top_k
            )

            for chunk in fallback_chunks:

                if chunk.id not in existing_ids:

                    results.append(
                        SearchResult(
                            chunk=chunk,
                            score=0.0
                        )
                    )

                if len(results) >= top_k:
                    break

        return results[:top_k]

    def _fallback_chunks(
        self,
        count: int
    ) -> List[Chunk]:

        """
        Select useful chunks when lexical search has no
        meaningful result.

        Preference:
            1. Files with common entry-point names
            2. Classes/functions
            3. Earlier chunks
        """

        preferred_names = {
            "app.py",
            "main.py",
            "server.py",
            "manage.py",
            "index.py",
            "run.py",
            "README.md",
            "package.json",
            "requirements.txt",
        }

        preferred = []
        others = []

        for chunk in self.chunks:

            filename = chunk.file_path.split("/")[-1]
            filename = filename.split("\\")[-1]

            if filename.lower() in {
                name.lower()
                for name in preferred_names
            }:

                preferred.append(chunk)

            else:
                others.append(chunk)

        selected = []

        for chunk in preferred:

            if chunk not in selected:

                selected.append(chunk)

            if len(selected) >= count:
                return selected

        for chunk in others:

            if chunk not in selected:

                selected.append(chunk)

            if len(selected) >= count:
                break

        return selected