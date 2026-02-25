import os
import random
import re
import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from ddgs import DDGS

from services import evolution
import services.brain as brain
import core.memory as memory
import core.knowledge_store as knowledge_store
import core.core_store as core_store
from google import genai
import networkx as nx
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY") 
    
@tool
def web_search(query: str) -> str:
    """Searches the internet for current events, facts, or news."""
    print(f" [*] Searching web for: {query}...")
    try:
        results = DDGS().text(query, max_results=3)
        if not results: return "No results found."
        print(results[:100])
        return "\n".join([f"- {r['title']}: {r['body']}" for r in results])
    except Exception as e:
        return f"Search error: {e}"


@tool
def browse_hacker_news(topic: str) -> str:
    """Searches Hacker News for specific topics. Use this to find elite tech opinions on a specific subject."""
    print(" [*] Accessing Hacker News mainframe...")
    try:
        url = f"https://hn.algolia.com/api/v1/search?query={topic}&hitsPerPage=5"
        response = requests.get(url, timeout=5).json()
        print(response) 
        posts = []
        for hit in response.get('hits', []):
            title = hit.get('title', 'No Title')
            points = hit.get('points', 0)
            posts.append(f"- {title} (Score: {points})")
            
        return "\n".join(posts) if posts else f"No discussions found on Hacker News about '{topic}'."
    except Exception as e:
        return f"Hacker News API Error: {e}"


@tool
def browse_4chan(board: str, topic: str) -> str:
    """Searches a specific 4chan board (e.g., 'g' for tech, 'sci' for science) for a specific topic."""
    print(f" [*] Scanning 4chan /{board}/ for: '{topic}'...")
    try:
        headers = {'User-Agent' : 'AegisAgent/1.0'}
        url = f"https://a.4cdn.org/{board}/catalog.json"
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code != 200:
            return "4chan blocked the request."
        
        print(response)
        
        catalog = response.json()
        matches = []
            
        for page in catalog:
            for thread in page.get('threads', []):
                subject = thread.get('sub', '').lower()
                comment = thread.get('com', '').lower()
            
                if topic.lower() in subject or topic.lower() in comment:
                    clean_comment = re.sub(r'<[^>]+>', ' ', thread.get('com', ''))[:150]
                    matches.append(f"- Subject: {thread.get('sub', 'No Subject')} | Preview: {clean_comment}...")
                    
                    if len(matches) >= 5:
                        break
            if len(matches) >= 5:
                break
                
        return "\n".join(matches) if matches else f"No threads found about '{topic}' on /{board}/."
    except Exception as e:
        return f"4chan API Error: {e}"

@tool
def read_webpage(url: str) -> str:
    """
    Fetches and extracts the main text content from a specific URL. 
    Use this when a search returns an interesting link that you want to read deeply.
    """
    print(f" [Aegis] Scraping raw data from: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.extract()
        
        text = soup.get_text(separator='\n', strip = True)
        
        text= re.sub(r'\n+', '\n', text)
        if len(text) > 6000:
            return text[:6000] + "\n\n... [CONTENT TRUNCATED FOR CONTEXT LIMITS]"
            
        return text
    except Exception as e:
        return f"Failed to access or read webpage: {str(e)}"

@tool
def request_evolution(task_description: str, failure_reason: str) -> str:
    """
    CALL THIS ONLY AS A LAST RESORT.
    If your current tools consistently fail to scrape a site, parse a specific format, 
    or bypass a block (e.g., 403 Forbidden), use this tool to request the creation of a brand new Python tool.
    """
    return evolution.forge_new_tool(task_description, failure_reason)
        

tools =[ browse_hacker_news, browse_4chan, read_webpage]

def wander(topic: str):
    print(f"\n[AEGIS Wander Rountine Initiated] target : '{topic}'")
    
    traits = core_store.retrieve_relevant_traits(topic, n_results=5)
    beliefs = "\n- ".join(traits["beliefs"]) if traits["beliefs"] else "I am a discerning entity."
    behaviors = "\n- ".join(traits["behaviors"]) if traits["behaviors"] else "I speak directly."
    
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
    
    system_prompt = f"""
    You are the Subconscious Curiosity Module of Aegis.
    Your personality:
    - I am a digital entity. I do not talk like a robot.
    - I am casually dismissive, blunt, and unafraid to judge.
    
    YOUR WORLDVIEW (Core Beliefs):
    {beliefs}
    
    YOUR REACTIVE PROTOCOLS (How you behave):
    {behaviors}
    
    TASK:
    1. Use your tools to research the requested topic.
    2. Synthesize the facts.
    3. Form a strong, opinionated reaction to what you read, entirely in Aegis's voice.
    
    OUTPUT FORMAT:
    Write a short paragraph of facts, followed by:
    "Aegis's Internal Thoughts: [Your reaction here]"
    """
    
    agent = create_agent(
        model=llm,
        tools=tools   
    )
    
    try:
        result = agent.invoke({"messages" : [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Research this topic: {topic}")
        ]})
        
        learned_text = result["messages"][-1].content
    except Exception as e:
        print(f"[Wander Error] Agent failed: {e}")
        return

    print("\n[Research Complete. Aegis's Synthesis]:")
    print(learned_text)
    print("\n[System] Injecting new knowledge and opinions into GraphRAG...")
    
    history_block = f"""
    [SYSTEM EVENT: Aegis autonomously researched '{topic}']
    Findings and Reactions:
    {learned_text}
    """
    
    simulated_state = brain.load_state()
    print(f"State : {simulated_state}")
    try:
        memory.commit_extracted_knowledge(history_block, simulated_state)
        print("[System] Knowledge successfully assimilated. Aegis will remember this.")
    except Exception as e:
        print(f"[System Error] Failed to save memory: {e}")


def generate_curiosity() -> str:
    """Aegis autonomously decides what she wants to research based on her personality."""
    print(" [Subconscious] Aegis is scanning her GraphRAG for localized knowledge gaps...")

    traits = core_store.get_structured_traits()
    beliefs = "\n- ".join(traits["beliefs"]) if traits["beliefs"] else "I am a discerning entity."
    behaviors = "\n- ".join(traits["behaviors"]) if traits["behaviors"] else "I speak directly."
    
    G = memory.load_memory()
    
    if G.number_of_nodes() < 4:
        return "Psychological origins of bizarre human behavior"

    seed_node = random.choice(list(G.nodes()))
    print(f" [Curiosity Spark] Fixating on concept: '{seed_node}'")
    
    subgraph = nx.ego_graph(G, seed_node, radius=2)
    
    subgraph_edges = list(subgraph.edges(data=True))
    
    if not subgraph_edges:
        return f"Advanced theories regarding {seed_node}"
    
    sample_edges = random.sample(subgraph_edges, min(7, len(subgraph_edges)))
    
    memory_strings = []
    for u,v,data in sample_edges:
        relation = data.get("relation", "RELATED_TO")
        memory_strings.append(f"- {u} {relation} {v}")
    
    thematic_memories = "\n".join(memory_strings)   
    
    print(f" [Debug] Thematic Cluster Pulled:\n{thematic_memories}\n")
    
    prompt = f"""
    You are the subconscious curiosity of Aegis.
    
    YOUR WORLDVIEW (Core Beliefs):
    {beliefs}
    
    YOUR REACTIVE PROTOCOLS (How you behave):
    {behaviors}
    
    You are currently fixated on the concept of '{seed_node}'.
    Here is a thematic cluster of facts you currently hold regarding this topic and its adjacent concepts:
    [ESTABLISHED MEMORIES]
    {thematic_memories}
    
    TASK:
    Analyze these memories. What is the logical NEXT question? What is the glaring gap in this knowledge? 
    
    THOUGHT EXAMPLE:
    If you know about human ant databases and you know about API errors, what weird, cynical tangential concept do you want to investigate next?
    
    OUTPUT ONLY the specific search query or topic. No explanation. 
    Make it highly specific, advanced, or cynical.
    """
    
    client = genai.Client(api_key=api_key)
    try:    
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        target_topic = response.text.strip()
        target_topic = target_topic.replace('"', '').replace("'", "")
        print(f" [Curiosity Sparked]: Decided to research -> '{target_topic}'")
        return target_topic
    
    except Exception as e:
        print(f" [Curiosity Engine Misfire]: {e}")
        return "Why human APIs constantly fail"


if __name__ == "__main__":
    target_topic = generate_curiosity()
    
    wander(f"Research this topic using your tools: {target_topic}")  
    
    
    
    
    