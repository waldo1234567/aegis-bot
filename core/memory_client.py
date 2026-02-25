from core.memory_daemon import get_daemon, AddEdgeEvent, AddNodesEvent

async def commit_edges(edges: list[dict], new_nodes: list[str] | None = None):
    daemon = get_daemon()

    if new_nodes:
        await daemon.push(AddNodesEvent(nodes=new_nodes))

    for edge in edges:
        await daemon.push(AddEdgeEvent(
            source=edge["source"],
            relation=edge["relation"],
            target=edge["target"],
            valence=edge.get("valence", 0.5),
        ))
        
def commit_edges_sync(edges: list[dict], new_nodes: list[str] | None = None):
    daemon = get_daemon()

    if new_nodes:
        daemon.push_sync(AddNodesEvent(nodes=new_nodes))

    for edge in edges:
        daemon.push_sync(AddEdgeEvent(
            source=edge["source"],
            relation=edge["relation"],
            target=edge["target"],
            valence=edge.get("valence", 0.5),
        ))