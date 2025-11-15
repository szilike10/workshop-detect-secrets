import asyncio
from agent_framework import ExecutorCompletedEvent, ExecutorInvokedEvent, ChatAgent, WorkflowBuilder

from domain.agents.chunk_agregator import ChunksAgregatorExec
from domain.agents.chunk_exporter import ChunksExporterExec
from domain.agents.secrets_detector import SecretsDetectorExec
from domain.settings import settings
from domain.logging import logger
from domain.utils import CustomResponseEvent

async def init_github_mcp():
    if settings.github_mcp_server is None:
        raise RuntimeError("GitHub MCP server tool was not initialized in settings.")
    await settings.github_mcp_server.connect()
    logger.info("GitHub MCP connected")

def init_secret_detector_agents(agents_count: int) -> list[SecretsDetectorExec]:
    """
    Spawn shard-aware detector agents. Returns an empty list when count < 1.
    """
    if agents_count < 1:
        return []

    return [
        SecretsDetectorExec(
            chat_client=settings.chat_client,
            id=f"SecretsDetector{idx}",
            my_shard=idx,
            total_agents=agents_count,
        )
        for idx in range(agents_count)
    ]

async def run_secrets_detector():
    await init_github_mcp()
    secrets_detector_agents = init_secret_detector_agents(agents_count=settings.secret_detector_agents_count)
    exporter = ChunksExporterExec(id="ChunkExporterAgent", github_mcp_server=settings.github_mcp_server, chat_client=settings.chat_client)
    aggregator = ChunksAgregatorExec(id="ChunksAgregatorAgent", github_mcp_server=settings.github_mcp_server)
    builder = WorkflowBuilder()
    builder.set_start_executor(exporter)
    builder.add_fan_out_edges(exporter,  secrets_detector_agents)
    builder.add_fan_in_edges( secrets_detector_agents, aggregator)
    workflow = builder.build()
    async for event in workflow.run_stream(""):
        match event:
            case CustomResponseEvent() as output:
                logger.info("Secrets detector workflow finished!")
            case ExecutorInvokedEvent() as invoke:
                logger.info("Starting %s", invoke.executor_id)
            case ExecutorCompletedEvent() as complete:
                logger.info("Completed %s: %s", complete.executor_id, complete.data)


def start():
    asyncio.run(run_secrets_detector())

if __name__ == "__main__":
    asyncio.run(run_secrets_detector())

    
