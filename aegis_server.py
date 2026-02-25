import os

from flask import Flask, request, jsonify
import services.brain as brain 
import json
import core.memory as memory
import google.genai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")


client = genai.Client(api_key=api_key)
app = Flask(__name__)

@app.route('/aegis-link', methods=['POST']) # type: ignore
def handle_reddit_event():
    data = request.json
    print(f"\n[Neural Link] Received transmission from Reddit")
    
    post_title = data.get('title', 'No Title')
    post_body = data.get('body', '')
    author = data.get('author', 'unknown')
    
    simulated_input = f"Reddit User u/{author} posted in the subreddit: '{post_title}'. Content: {post_body}"
    
    state = brain.load_state()
    chat_buffer = brain.load_short_term()
    
    reply = brain.generate_response(simulated_input, state, chat_buffer)
    
    print(f"[Aegis Response]: {reply}")
    
    chat_buffer.append(f"System (Reddit): {simulated_input}")
    chat_buffer.append(f"Aegis: {reply}")
    brain.save_short_term(chat_buffer[-20:])
    
    
@app.route('/aegis-learn', methods=['POST'])
def handle_deep_learning():
    data = request.json
    batch_posts = data.get('posts', [])
    
    print(f"\n[Subconscious] Processing batch of {len(batch_posts)} posts for long-term memory...")
    
    current_state = brain.load_state()
    
    context_block = "Aegis recently browsed the subreddit and observed these discussions:\n"
    for p in batch_posts:
        context_block += f"- u/{p['author']} posted: {p['title']}\n"
    
    memory.update_graph(context_block, current_state)
    
    return jsonify({"status": "assimilated"})
    
    
if __name__ == '__main__':
    print("Aegis Brain-Server active on port 8000...")
    app.run(port=8000)
    