import requests

API_URL = "http://127.0.0.1:8000/api/chat"

print("--- AEGIS TERMINAL LINK ONLINE ---")
while True:
    user_input = input("Waldo: ")
    if user_input.lower() in ['quit', 'exit']:
        break
    
    try:
        response = requests.post(API_URL, json={"user_input": user_input, "user_id": "Waldo"})
        data = response.json()
        
        print(f"\nAegis: {data['reply']}")
        print(f"[System] VAD State -> Valence: {data['valence']:.2f} | Arousal: {data['arousal']:.2f}\n")
    except requests.exceptions.ConnectionError:
        print("[Error] Could not connect to the God Engine. Is main.py running?")