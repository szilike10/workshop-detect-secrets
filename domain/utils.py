import hashlib
import uuid
from agent_framework import (
    WorkflowEvent,
)

from domain.models import (
    TextChunk,
    SecretsDetectorExecutorResponse
)
DETECTED_SECRETS_RESULT_KEY = "detected_secrets"

class CustomResponseEvent(WorkflowEvent):
    def __init__(self, result: list[SecretsDetectorExecutorResponse]):
        super().__init__(result)


class ChunkConsistencyHelper:
    """Helper for deterministic chunk identifiers and shard assignments."""

    NAMESPACE = uuid.UUID("876de125-4386-442b-9e88-d40dfbbb301d")

    def stable_uuid(self, any_string: str) -> str:
        """
        Return a deterministic UUID for the input string.

        Normalizing the string keeps IDs stable even if callers change case
        or add stray whitespace.
        """
        any_string = any_string.strip().lower()
        return str(uuid.uuid5(self.NAMESPACE, any_string))

    def shard_for_chunk(self, chunk: TextChunk, total_agents: int) -> int:
        """
        Pick which worker (0..total_agents-1) should handle this chunk.

        How it works (in plain words):
        - Build a key from the file name and line range (e.g., "app.py|120|180").
        - Hash that key with SHA-256 (gives a big, stable number).
        - Take that number modulo total_agents to get a shard index.

        Inputs:
        - chunk: has `source_file: str` and `line_span: (start:int, end:int)`.
        - total_agents: number of workers; must be >= 1.

        Guarantees:
        - Same chunk → same shard index (deterministic).
        - Result r is an int with 0 <= r < total_agents.

        Example:
        >> shard_for_chunk(TextChunk(source_file="a.py", line_span=(10, 30)), total_agents=3)
        2
        """
        h = hashlib.sha256(f"{chunk.source_file}|{chunk.line_span}".encode()).digest()
        return int.from_bytes(h[:4], "big") % total_agents

chunk_consistency_helper = ChunkConsistencyHelper()