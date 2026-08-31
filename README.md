# AI-Native Retail Analytics Agent & In-Process OLAP Engine

An in-process, high-performance retail analytics warehouse and conversational query agent powered by **DuckDB**, **PydanticAI**, and **Graph Theory (Louvain Community Detection)**.

## Architecture

- **In-Process Vectorized OLAP (DuckDB):** Sub-millisecond analytical aggregations directly in-memory with permanent `read_only=True` connection isolation for zero SQL-injection risk.
- **Plan-Execute-Validate (PEV) Query Agent:** PydanticAI agent with schema introspection and self-healing SQL execution loops.
- **Sandboxed Python Runtime:** AST-filtered execution environment for custom statistical and time-series computations with strict builtin/import whitelisting.
- **Market Basket Graph Mining:** NetworkX Louvain modularity clustering discovering co-purchase affinities and natural trade communities for shelf-zoning optimization.

## Quickstart

```bash
# Set your API Key
export LLM_API_KEY="your-api-key"

# Run Co-Purchase Graph Mining
python3 src/analytics/graph_mining.py
```
