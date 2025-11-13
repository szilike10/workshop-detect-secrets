from agent_framework.openai import OpenAIChatClient
from agent_framework import MCPStdioTool, ChatAgent
import os
from dotenv import load_dotenv
import hashlib
import uuid
import asyncio
import json
from pathlib import Path
from typing import List, Dict

from agent_framework import (
    handler, Executor, ChatAgent, 
    ExecutorInvokedEvent, ExecutorCompletedEvent,
    WorkflowEvent, WorkflowBuilder, WorkflowContext, 
)
from domain.models import (
    TextChunk, PRFileList, PRFileInfo, LineComment, 
    SecretsDetectorExecutorResponse, EmptySecretsDetectorExecutorResponseFactory, 
)

load_dotenv(dotenv_path=".env")
chat_client = OpenAIChatClient(api_key=os.getenv("OPENAI_API_KEY"), model_id=os.getenv("MODEL_ID"))
GITHUB_TOKEN = os.getenv("GH_TOKEN_FULL_PERMISIONS")
GITHUB_REPO = os.getenv("GH_REPO")
GITHUB_OWNER = os.getenv("GH_OWNER")
TARGET_PR_NUMBER = os.getenv("TARGET_PR_NUMBER")

if '/' in GITHUB_REPO:
    GITHUB_OWNER, GITHUB_REPO = GITHUB_REPO.split('/', 1)

# Specify the toolsets we want. There are far more, but only these are needed for this example.
# And we don't want to bloat the agent's context with unnecessary tools.
toolsets = "context,pull_requests" 

print("Using GitHub repo:", f"{GITHUB_REPO}")

async def create_github_mcp_server():
    github_mcp = MCPStdioTool(
        name="GitHubMCP",
        command="docker",
        args=[
            "run", "-i", "--rm",
            "-e", f"GITHUB_PERSONAL_ACCESS_TOKEN={GITHUB_TOKEN}", 
            f"-e", f"GITHUB_TOOLSETS={toolsets}",
            "ghcr.io/github/github-mcp-server"
        ],
        chat_client=chat_client,
    )
    await github_mcp.connect()
    print("GitHub MCP connected")
    return github_mcp


def split_file_by_newlines(
    file_path: str,
    newlines_per_chunk: int,
    pull_request_number: str = "",
    repo: str = "",
    repo_owner: str = "",
) -> List[Dict]:
    """ 
    Split a text file into chunks containing a fixed number of newline separators.
    - Normalizes all line endings to '\n' first.
    - `original_lines_interval` is 1-based and inclusive.
    - If the last chunk has fewer lines (fewer '\n' separators), it's still included.
    """

    if "http" in file_path:
        # If it's a web URL and not a local file, fetch the content
        import requests
        
        filepath_github_raw = file_path.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")

        r = requests.get(filepath_github_raw)
        r.raise_for_status()

        text = r.text.replace("\r\n", "\n").replace("\r", "\n")
        original_file = file_path.split("/")[-1]
    else:
        p = Path(file_path)
        original_file = p.name

        # Normalize all newlines to '\n' to ensure consistent splitting
        text = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")

    # Split strictly by '\n'
    lines = text.split("\n")  # newline characters are removed by split
    total_lines = len(lines)

    chunks: List[Dict] = []

    # Step through in blocks of `newlines_per_chunk` lines
    for i in range(0, total_lines, newlines_per_chunk):
        block = lines[i : i + newlines_per_chunk]
        if not block:
            continue

        # Reconstruct the chunk string with '\n' between lines.
        # IMPORTANT: we DO NOT append a trailing '\n' at the end of the chunk.
        chunk_text = "\n".join(block)

        # 1-based line numbers for the original interval
        start_line = i + 1
        end_line = i + len(block)

        chunks.append({
            "chunk": chunk_text,
            "original_lines_interval": [start_line, end_line],
            "original_file": original_file,
            "pull_request_number": pull_request_number,
            "repo": repo,
            "repo_owner": repo_owner,
        })

    return chunks


NAMESPACE = uuid.UUID("876de125-4386-442b-9e88-d40dfbbb301d")  # pick once & keep


def stable_uuid(s: str) -> str:
    s = s.strip().lower()  # normalize to avoid accidental mismatches
    return str(uuid.uuid5(NAMESPACE, s))

def shard_for_chunk(chunk: TextChunk, total_agents: int) -> int:
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


DETECTED_SECRETS_RESULT_KEY = "detected_secrets"


class CustomResponseEvent(WorkflowEvent):
    def __init__(self, result: list[SecretsDetectorExecutorResponse]):
        super().__init__(result)


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
        if shard_for_chunk(chunk, self.total_agents) != self.my_shard:
            return
        prompt = self.create_prompt_from_chunk(chunk)
        key = stable_uuid(repr((chunk.source_file, chunk.line_span)))

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


class ChunksExporterExec(Executor):
    agent_instructions = f"""
        You are a helpful assistant. Retrieve all files included in an open pull request from the GitHub repository '{GITHUB_OWNER}/{GITHUB_REPO}'.
        Respond only with a list of direct links (URLs) to the files changed or added in the pull request along with the necessary extra information (owner, repo, branch).
        """

    def __init__(self, id, github_mcp_server, chat_client: OpenAIChatClient):
        self.id = id
        # Define the inner agent which will extract the PR files
        self.github_pr_extraction_agent = ChatAgent(
            chat_client=chat_client,
            instructions=self.agent_instructions,
            name="PullRequestExtractorAgent",
            tools=[*github_mcp_server.functions], 
            response_format=PRFileList
        )
        super().__init__(id=id)

    @handler
    async def run(self, _: str,ctx: WorkflowContext[TextChunk]) -> None:
        """Sends input test chunks"""
        final_results = []
        await ctx.set_shared_state(DETECTED_SECRETS_RESULT_KEY, final_results)

        files: List[PRFileInfo] = []
        while not files:

            pr_files_response = await self.github_pr_extraction_agent.run(
                f"Get me all the files involved in the PR with number {TARGET_PR_NUMBER}.",
                response_format=PRFileList
            )

            files: List[PRFileInfo] = pr_files_response.value.files
            if not files:
                print("No files extracted, retrying...")
                continue
            for file in files:
                # Sometimes the agent outputs the full URL, we need only the filename and we build the URL ourselves
                file.source_file = file.source_file.split("/")[-1]
            print(f"Files in PR: {[file.source_file for file in files]}")

        input_chunks = []
        for file in files:
            try:
                filepath = f"https://raw.githubusercontent.com/{file.repo_owner}/{file.repo}/refs/heads/{file.source_branch}/{file.source_file}"
                print(f"Processing file: {filepath}")
                chunks = split_file_by_newlines(
                    file_path=filepath,
                    newlines_per_chunk=10,
                    pull_request_number=file.pull_request_number,
                    repo=file.repo,
                    repo_owner=file.repo_owner
                )
                input_chunks.extend(chunks)
            except Exception as e:
                print(f"Error processing file {file.source_file}: {e}")

        for chunk in input_chunks:
            start, end = chunk["original_lines_interval"]
            text_chunk = TextChunk(
                chunk=str(chunk["chunk"]), 
                line_span=(int(start), int(end)), 
                source_file=str(chunk["original_file"]),
                repo=str(chunk["repo"]),
                repo_owner=str(chunk["repo_owner"]),
                pull_request_number=str(chunk["pull_request_number"])
            )
            key = stable_uuid(repr((text_chunk.source_file, text_chunk.line_span)))
            await ctx.set_shared_state(key, False)
            await ctx.send_message(text_chunk)


class ChunksAgregatorExec(Executor):

    def __init__(self, id, github_mcp_server):
         self.id = id
         self.github_mcp_client = ChatAgent(
                chat_client=chat_client,
                instructions=(
                    "You are a helpful assistant that writes review comments on GitHub PRs. "
                    "Respond with 'SUCCESS' if the operation succeeded, otherwise 'FAILURE: <reason>'."
                    "Make sure to follow the exact instructions you receive and make sure to ALWAYS INCLUDE LINE NUMBER in the request."
                ),
                name="GithubCodeReviewerAgent",
                tools=[*github_mcp_server.functions],
            )
         super().__init__(id=id)

    async def _call_github_mcp_client(self, detected_secret: SecretsDetectorExecutorResponse, line_comment: LineComment):
        prompt = (
            f"Add the comment '{line_comment.comment}' to pull request "
            f"#{detected_secret.pull_request_number} in repository "
            f"'{detected_secret.repo_owner}/{detected_secret.repo}', "
            f"file '{detected_secret.original_file}', at line {line_comment.line_number}. "
            f"MAKE SURE TO INCLUDE THE LINE NUMBER IN THE REQUEST."
            f"If there is no active review, create one."
        )
        print(f"Adding comment for file '{detected_secret.original_file}' at line {line_comment.line_number}")
        try:
            return await self.github_mcp_client.run(prompt)
        except Exception as e:
            return f"FAILURE: {type(e).__name__}: {e}"

    @handler
    async def run(self, detected_secrets: list[SecretsDetectorExecutorResponse] ,ctx: WorkflowContext[None]) -> None:
        """Sends input test chunks"""
        filtered_nonempty = [secret for secret in detected_secrets if not secret.is_empty()]
        for elem in filtered_nonempty:
            for comment in elem.comments:
                await self._call_github_mcp_client(detected_secret=elem, line_comment=comment)
        await ctx.add_event(CustomResponseEvent(filtered_nonempty))

class ImprovedChunksAgregatorExec(ChunksAgregatorExec):

    def __init__(self, id, github_mcp_server):
         super().__init__(id=id, github_mcp_server=github_mcp_server)

    async def _bounded_call(
        self,
        sem: asyncio.Semaphore,
        detected_secret: SecretsDetectorExecutorResponse,
        line_comment: LineComment,
    ):
        async with sem:
            try:
                return await self._call_github_mcp_client(detected_secret, line_comment)
            except Exception as e:
                # Surface failures but don’t crash the whole batch
                return f"FAILURE: {type(e).__name__}: {e}"
    
    @handler
    async def run(self, detected_secrets: list[SecretsDetectorExecutorResponse] ,ctx: WorkflowContext[None]) -> None:
        """Sends input test chunks"""
        sem = asyncio.Semaphore(self.max_concurrency)
        tasks: list[asyncio.Task] = []
        filtered_nonempty = [secret for secret in detected_secrets if not secret.is_empty()]
        for elem in filtered_nonempty:
            for comment in elem.comments:
                tasks.append(asyncio.create_task(self._bounded_call(sem, elem, comment)))

        # Fire all at once and wait for completion
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # (Optional) summarize successes/failures if you want to emit a richer event
        await ctx.add_event(CustomResponseEvent({
            "processed_items": len(tasks),
            "successes": sum(1 for r in results if isinstance(r, str) and r.startswith("SUCCESS")),
            "failures": [r for r in results if not (isinstance(r, str) and r.startswith("SUCCESS"))],
            "secrets": filtered_nonempty,
        }))


def create_workflow(chat_client: OpenAIChatClient, github_mcp: MCPStdioTool):
    total_agents=3
    secrets_detector_1 = SecretsDetectorExec(chat_client, id="SecretsDetector1", my_shard=0, total_agents=total_agents)
    secrets_detector_2 = SecretsDetectorExec(chat_client, id="SecretsDetector2", my_shard=1, total_agents=total_agents)
    secrets_detector_3 = SecretsDetectorExec(chat_client, id="SecretsDetector3", my_shard=2, total_agents=total_agents)
    exporter = ChunksExporterExec(id="ChunkExporterAgent", github_mcp_server=github_mcp, chat_client=chat_client)
    aggregator = ChunksAgregatorExec(id="ChunksAgregatorAgent", github_mcp_server=github_mcp)
    builder = WorkflowBuilder()
    builder.set_start_executor(exporter)
    builder.add_fan_out_edges(exporter, [secrets_detector_1, secrets_detector_2, secrets_detector_3])
    builder.add_fan_in_edges([secrets_detector_1,
                            secrets_detector_2,
                            secrets_detector_3],
                            aggregator)

    workflow = builder.build()

    return workflow

def visualize_workflow(workflow):
    from agent_framework import WorkflowViz
    
    viz = WorkflowViz(workflow)
    try:
        from graphviz import Source
        from IPython.display import display
        src = Source(viz.to_digraph())
        display(src)
        src.render('workflow_diagram', format='png', view=True)
    except Exception as e:
        print(f"Error rendering diagram: {e}")
        print(viz.to_mermaid())
    

async def execute_workflow(workflow):
    async for event in workflow.run_stream(""):
        match event:
            case CustomResponseEvent() as output:
                print(f"Workflow finished")
            case ExecutorInvokedEvent() as invoke:
                print(f"Starting {invoke.executor_id}")
            case ExecutorCompletedEvent() as complete:
                print(f"Completed {complete.executor_id}: {complete.data}")


async def main():
    github_mcp = await create_github_mcp_server()
    try:
        workflow = create_workflow(chat_client, github_mcp)
        # visualize_workflow(workflow)
        await execute_workflow(workflow)
    finally:
        await github_mcp.close()


if __name__ == "__main__":
    asyncio.run(main())