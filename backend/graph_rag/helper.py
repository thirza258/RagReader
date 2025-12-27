import json
import networkx as nx
from typing import List, Tuple, Dict, Any
from openai import OpenAI

def extract_graph_data(text: str, client: OpenAI, model: str = "gpt-4o") -> Dict[str, Any]:
    """
    Uses the LLM to parse text into Nodes (entities) and Edges (relationships).
    Returns a JSON dict.
    """
    system_prompt = """
    You are an expert Knowledge Graph extractor.
    Analyze the provided text and extract:
    1. Entities (Nodes): People, Places, Organizations, Concepts, etc.
    2. Relationships (Edges): How these entities interact.

    Return strictly valid JSON in this format:
    {
      "nodes": [
        {"id": "Entity Name", "type": "Person/Concept/etc"}
      ],
      "edges": [
        {"source": "Entity Name", "target": "Entity Name", "relation": "relationship description"}
      ]
    }
    """

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            response_format={"type": "json_object"},
            temperature=0  # Deterministic output
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        print(f"LLM Extraction Error: {e}")
        return {"nodes": [], "edges": []}

def text_to_networkx(text: str, client: OpenAI, model: str = "gpt-4o") -> nx.Graph:
    """
    Orchestrator that turns text directly into a NetworkX graph object.
    """
    # 1. Extract Data via LLM
    data = extract_graph_data(text, client, model)
    
    # 2. Initialize Graph
    G = nx.Graph()

    # 3. Add Nodes
    for node in data.get("nodes", []):
        # We store the 'type' as a node attribute
        G.add_node(node["id"], label=node.get("type", "Unknown"))

    # 4. Add Edges
    for edge in data.get("edges", []):
        source = edge["source"]
        target = edge["target"]
        relation = edge["relation"]
        
        # In NetworkX, we can add edge attributes (like the relationship description)
        G.add_edge(source, target, relation=relation)
        
    return G

def parse_network(network: nx.Graph) -> Tuple[List[Any], List[Any]]:
    """
    Utility to inspect the graph.
    Returns list of Nodes (with attributes) and Edges (with attributes).
    """
    # data=True includes the attributes (like 'label' or 'relation')
    nodes = list(network.nodes(data=True))
    edges = list(network.edges(data=True))
    return nodes, edges