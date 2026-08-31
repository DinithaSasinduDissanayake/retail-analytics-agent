from collections import Counter
import duckdb
import pandas as pd
try:
    import networkx as nx
    from networkx.algorithms.community import louvain_communities
except ImportError:
    nx = None

def mine_co_purchase_communities(db_path: str = "data/warehouse.db", min_weight: int = 2):
    """Build product co-purchase affinity graph and detect trade communities via Louvain clustering."""
    conn = duckdb.connect(db_path, read_only=True)
    df_lines = conn.execute("SELECT docket_id, stock_id FROM DocketLine").df()
    df_stock = conn.execute("SELECT stock_id, description FROM Stock").df()
    conn.close()
    
    stock_map = dict(zip(df_stock['stock_id'], df_stock['description']))
    baskets = df_lines.groupby('docket_id')['stock_id'].apply(list)
    multi_item = baskets[baskets.apply(len) > 1]
    
    edge_weights = Counter()
    for items in multi_item:
        items = sorted(set(items))
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                edge_weights[(items[i], items[j])] += 1
                
    if nx is None:
        return {"error": "networkx not installed"}
        
    G = nx.Graph()
    for (a, b), weight in edge_weights.items():
        if weight >= min_weight:
            G.add_edge(a, b, weight=weight)
            
    communities = list(louvain_communities(G, weight='weight', seed=42))
    results = []
    for idx, c in enumerate(communities, 1):
        names = [stock_map.get(sku, sku) for sku in c]
        results.append({"community_id": idx, "size": len(c), "products": names})
    return results

if __name__ == "__main__":
    comms = mine_co_purchase_communities()
    print("Detected Trade Communities:", comms)
