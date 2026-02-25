import requests
import sys

API_URL = "http://127.0.0.1:8000/api/chat"

def main():
    print("==================================================")
    print(" AEGIS NEURAL LINK ESTABLISHED")
    print(" Type 'exit' to sever connection.")
    print("==================================================\n")
    
    while True:
        try:
            user_input = input("Waldo: ")
            if user_input.lower() in ['exit', 'quit']:
                print("Severing link...")
                break
            if not user_input.strip():
                continue
            
            response = requests.post(API_URL, json={
                "user_input": user_input,
                "user_id": "Waldo"
            })
            
            if response.status_code == 200:
                data = response.json()
                reply = data.get("reply", "[Silence]")
                v = data.get("valence", 0.5)
                a = data.get("arousal", 0.5)
                d = data.get("dominance", 0.5)
                
                print(f"\nAegis: {reply}")
                print(f" [VAD State: Valence {v:.2f} | Arousal {a:.2f} | Dominance {d:.2f}]\n")
            else:
                print(f"\n[System Error] Server returned {response.status_code}: {response.text}\n")
        
        except requests.exceptions.ConnectionError:
            print("\n[System Error] Cannot reach Aegis. Is the Uvicorn server running?")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nSevering link...")
            break

if __name__ == "__main__":
    main()