import urllib.request
import json

url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        btc_price = data['bitcoin']['usd']
        amount = 1000 / btc_price
        
        with open('test_output.txt', 'w') as f:
            f.write(f"Current BTC Price: ${btc_price}\n")
            f.write(f"$1000 buys: {amount} BTC\n")
        print("Success. Output written to test_output.txt")
except Exception as e:
    print(f"Error: {e}")
