from collections import Counter
import os
from pathlib import Path
import duckdb

try:
    import networkx as nx
    from networkx.algorithms.community import louvain_communities, modularity
except ImportError:
    nx = None
    louvain_communities = None
    modularity = None


def mine_co_purchase_communities(
    db_path: Path | str | None = None,
    min_weight: int = 2,
) -> dict:
    """Build product co-purchase affinity graph and detect trade communities via Louvain clustering."""
    if nx is None:
        return {"error": "networkx not installed"}

    resolved = Path(db_path) if db_path is not None else Path(os.getenv("WAREHOUSE_DB_PATH", "data/warehouse.db"))
    conn = duckdb.connect(str(resolved), read_only=True)
    try:
        df_lines = conn.execute("SELECT docket_id, stock_id FROM DocketLine").df()
        df_stock = conn.execute("SELECT stock_id, description FROM Stock").df()
    finally:
        conn.close()

    stock_map = dict(zip(df_stock["stock_id"], df_stock["description"]))
    baskets = df_lines.groupby("docket_id")["stock_id"].apply(list)
    multi_item = baskets[baskets.apply(len) > 1]

    edge_weights: Counter[tuple[str, str]] = Counter()
    for items in multi_item:
        unique_items = sorted(set(items))
        for i in range(len(unique_items)):
            for j in range(i + 1, len(unique_items)):
                edge_weights[(unique_items[i], unique_items[j])] += 1

    graph = nx.Graph()
    for (a, b), weight in edge_weights.items():
        if weight >= min_weight:
            graph.add_edge(a, b, weight=weight)

    if graph.number_of_nodes() == 0:
        return {"modularity": 0.0, "node_count": 0, "edge_count": 0, "communities": []}

    communities = list(louvain_communities(graph, weight="weight", seed=42))
    mod_score = round(float(modularity(graph, communities, weight="weight")), 4)

    formatted = []
    for idx, comm in enumerate(sorted(communities, key=len, reverse=True), 1):
        names = sorted(stock_map.get(sku, str(sku)) for sku in comm)
        formatted.append({"community_id": idx, "size": len(comm), "products": names})

    return {
        "modularity": mod_score,
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "communities": formatted,
    }


if __name__ == "__main__":
    result = mine_co_purchase_communities()
    print(f"Nodes: {result.get('node_count')}, Edges: {result.get('edge_count')}, Modularity: {result.get('modularity')}")
    for comm in result.get("communities", []):
        print(f"  Community {comm['community_id']} ({comm['size']} items): {', '.join(comm['products'])}")
