import os
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from src.agent.tools import duckdb_query, run_sandboxed_python

# Load API key strictly from environment variable (never hardcoded)
api_key = os.getenv("LLM_API_KEY", "mock-key-for-testing")
base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")

model = OpenAIChatModel(
    model_name=os.getenv("LLM_MODEL", "gpt-4o-mini"),
    api_key=api_key,
    base_url=base_url
)

SYSTEM_PROMPT = """You are an expert Retail Data Warehouse & Inventory Analytics Agent.
You assist retail decision makers by analyzing sales dockets, product inventory, and customer baskets.
Always execute queries against the read-only DuckDB warehouse and verify results before responding.
"""

retail_agent = Agent(
    model,
    system_prompt=SYSTEM_PROMPT,
    tools=[duckdb_query, run_sandboxed_python]
)
