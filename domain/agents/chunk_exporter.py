from pathlib import Path
from typing import Dict, List
from agent_framework import (
    handler, Executor, ChatAgent, WorkflowContext, 
)
from agent_framework.openai import OpenAIChatClient
from domain.settings import settings
from domain.models import (
    TextChunk, PRFileList, PRFileInfo
)
from domain.utils import DETECTED_SECRETS_RESULT_KEY, chunk_consistency_helper

from domain.utils import chunk_consistency_helper

class ChunksExporterExec(Executor):
    agent_instructions = f"""
        You are an assistant that lists files from the diff of a PR in {settings.github_owner}/{settings.github_repo} only. 
        Do not read the repo tree or base branch. 
        Exclude any file not present in this PR's changes.
        Return just an array of direct links (URLs) to the files that are involved in the pull request along with the necessary extra information (owner, repo, branch). No extra text.
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
    
    def split_file_by_newlines(
        self,
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

    @handler
    async def run(self, _: str,ctx: WorkflowContext[TextChunk]) -> None:
        """Sends input test chunks"""
        final_results = []
        await ctx.set_shared_state(DETECTED_SECRETS_RESULT_KEY, final_results)

        files: List[PRFileInfo] = []
        while not files:

            pr_files_response = await self.github_pr_extraction_agent.run(
                f"List files from the diff of PR #{settings.target_pr_number} only.",
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
                chunks = self.split_file_by_newlines(
                    file_path=f"https://raw.githubusercontent.com/{file.repo_owner}/{file.repo}/{file.source_branch}/{file.source_file}",
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
            key = chunk_consistency_helper.stable_uuid(repr((text_chunk.source_file, text_chunk.line_span)))
            await ctx.set_shared_state(key, False)
            await ctx.send_message(text_chunk)