import json
from agent_framework import (
    handler, Executor, ChatAgent, WorkflowContext, 
)
from agent_framework.openai import OpenAIChatClient

from domain.models import (
    TextChunk, LineComment, 
    SecretsDetectorExecutorResponse, EmptySecretsDetectorExecutorResponseFactory, 
)
from domain.utils import chunk_consistency_helper

from domain.models import TextChunk

class SecretsDetectorExec(Executor):
    agent: ChatAgent
    agent_instruction = """
        <instruction role="system">
        You are a code-secrets detector. Given a text CHUNK (with "\n" newlines) and its original line interval [START, END], return only a JSON array of findings. Flag lines that contain likely secrets (API keys/tokens, private keys, passwords, connection strings with creds, service-account JSON fields, auth headers) or PII (names paired with email/phone/IDs). Be precise; if unsure, don't flag. Ignore obvious placeholders.
        </instruction>
        <schema>
        Output exactly:
        [
        { "line_number": <int original line>, "comment": "<types comma-separated>. Please remove." }
        ]
        Return [] if nothing is found. No extra text.
        </schema>
        <procedure>
        1) Split CHUNK by "\n".
        2) For each line i (1-based), assess for secrets/PII using field names and context (e.g., "api_key", "token", "password", "private_key", DSN with user:pass, "Authorization: Bearer ...", service-account fields like private_key_id/private_key).
        3) If flagged, compute original line_number = START + i - 1.
        4) Emit JSON as per <schema>, comments short, no code excerpts.
        </procedure>
        <example>
        INPUT:
        START=4, END=7
        CHUNK:
        print("ok")
        "private_key_id": "f4f3c2e1d0b9a8f7e6d5c4b3a2918171",
        print("done")

        OUTPUT:
        [
        { "line_number": 5, "comment": "Private key identifier. Please remove." }
        ]
        </example>
    """

    def __init__(self, chat_client: OpenAIChatClient,  my_shard: int, total_agents: int, id: str = "secrets detector"):
        # Define the inner agent which will do the secrets detection
        agent = chat_client.create_agent(
            instructions=self.agent_instruction,
            name=f"SecretsDetectorAgent_{id}",
        )
        self.id = id
        self.agent = agent
        self.my_shard = my_shard
        self.total_agents = total_agents
        super().__init__(agent=agent, id=id)

    def create_prompt_from_chunk(self, chunk: TextChunk):
        prompt = f"""
            Please investigate and detect secrets existent in the chunk taken from the line intervals of the file {chunk.source_file}.
            INPUT
            START={chunk.line_span[0]}, END={chunk.line_span[1]}
            CHUNK:
            {chunk.text}
        """
        return prompt

    
    @handler
    async def run(self, chunk: TextChunk,ctx: WorkflowContext[SecretsDetectorExecutorResponse]) -> None:
        if chunk_consistency_helper.shard_for_chunk(chunk, self.total_agents) != self.my_shard:
            return
        prompt = self.create_prompt_from_chunk(chunk)
        key = chunk_consistency_helper.stable_uuid(repr((chunk.source_file, chunk.line_span)))

        async with ctx.shared_state.hold():
            chunk_processed = await ctx.shared_state.get_within_hold(key)
            if chunk_processed:
                await ctx.send_message(EmptySecretsDetectorExecutorResponseFactory.get_empty_secrets_detector())
                return
            await ctx.shared_state.set_within_hold(key, True)
        response = await self.agent.run(prompt)
        identified_problematic_lines = [LineComment(line_number=elem["line_number"], comment=elem["comment"]) for elem in json.loads(response.text)]
        await ctx.set_shared_state(key, True)
        await ctx.send_message(
            SecretsDetectorExecutorResponse(
                comments=identified_problematic_lines, 
                original_file=chunk.source_file, 
                executor_agent=self.id,
                repo=chunk.repo,
                repo_owner=chunk.repo_owner,
                pull_request_number=chunk.pull_request_number
        ))