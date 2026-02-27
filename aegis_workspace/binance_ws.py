import websocket
import json
import csv
import time

CSV_FILE = "order_book.csv"
MSG_LIMIT = 5
msg_count = 0

def on_message(ws, message):
    global msg_count
    data = json.loads(message)
    bids = data.get("bids", [])
    asks = data.get("asks", [])
    with open(CSV_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        top_bid = bids[0] if bids else [None, None]
        top_ask = asks[0] if asks else [None, None]
        writer.writerow([time.time(), top_bid[0], top_bid[1], top_ask[0], top_ask[1]])
    msg_count += 1
    if msg_count >= MSG_LIMIT:
        ws.close()

def on_error(ws, error):
    pass

def on_close(ws, close_status_code, close_msg):
    pass

def on_open(ws):
    with open(CSV_FILE, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "top_bid_price", "top_bid_qty", "top_ask_price", "top_ask_qty"])

if __name__ == "__main__":
    socket = "wss://stream.binance.com:9443/ws/btcusdt@depth5"
    ws = websocket.WebSocketApp(socket, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
    ws.run_forever()
