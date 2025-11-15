from agent_framework import (
    handler, Executor, ChatAgent, WorkflowContext, 
)

from domain.models import (LineComment, 
    SecretsDetectorExecutorResponse
)
from domain.utils import CustomResponseEvent
from domain.settings import settings


class ChunksAgregatorExec(Executor):

    def __init__(self, id, github_mcp_server):
         self.id = id
         self.github_mcp_client = ChatAgent(
                chat_client=settings.chat_client,
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