from flask import Flask, request, jsonify
import os
import ccxt
import math

app = Flask(__name__)

# --- Load Environment Variables ---
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
SECRET_KEY = os.getenv("SECRET_KEY", "test1234")

if not API_KEY or not API_SECRET:
    raise Exception("CRITICAL: Missing API_KEY or API_SECRET.")

# --- Initialize Exchange Connection for Binance Futures Testnet ---
try:
    print("Attempting to connect to Binance Futures Testnet...")
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'options': { 'defaultType': 'future' }
    })
    exchange.set_sandbox_mode(True)
    exchange.load_markets()
    print("SUCCESS: Connection to Binance Futures Testnet established.")
except Exception as e:
    raise Exception(f"Error initializing exchange connection: {e}")

@app.route('/')
def home():
    return "Webhook Bot for Binance Futures is live!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        print(f"Webhook received: {data}")
    except Exception as e:
        return jsonify({"status": "error", "message": f"Invalid JSON: {e}"}), 400

    if data.get("secret") != SECRET_KEY:
        return jsonify({"status": "error", "message": "Invalid secret key"}), 403

    symbol = data.get("symbol") # This will be 'ETHUSDT' from your webhook
    side = data.get("side")
    action = data.get("action")
    try:
        qty_pct = float(data.get("qty_pct", 0))
    except (ValueError, TypeError):
        qty_pct = 0

    if not symbol:
        return jsonify({"status": "error", "message": "Missing 'symbol' in webhook data"}), 400

    try:
        # --- BUY LOGIC (No changes needed here) ---
        if side == "buy":
            print(f"Processing BUY order for {symbol}...")
            balance = exchange.fetch_balance()
            quote_currency = "USDT"
            available_balance = balance['free'].get(quote_currency, 0)
            print(f"Available balance: {available_balance} {quote_currency}")
            if available_balance <= 1:
                return jsonify({"status": "error", "message": f"Insufficient balance."}), 400
            
            ticker = exchange.fetch_ticker(symbol)
            last_price = ticker.get('last')
            if last_price is None:
                return jsonify({"status": "error", "message": f"Could not get price for {symbol}."}), 400

            amount_in_usdt = available_balance * (qty_pct / 100)
            amount = amount_in_usdt / last_price
            
            print(f"Attempting to place market BUY order for {amount:.4f} {symbol} at ~${last_price}")
            order = exchange.create_market_buy_order(symbol, amount)
            print(f"SUCCESS: Buy Order executed.")
            return jsonify({"status": "success", "order": order}), 200

        # --- CLOSE LOGIC (FINAL, REVISED VERSION WITH THE FIX) ---
        elif action == "close":
            print(f"Processing CLOSE signal for {symbol}...")
            
            all_positions = exchange.fetch_positions()
            
            print(f"--- DEBUG: All positions fetched: {all_positions} ---")
            
            pos = None
            for p in all_positions:
                p_info_symbol = p.get('info', {}).get('symbol')
                # *** FIX APPLIED HERE: Access positionAmt from within 'info' dictionary ***
                p_position_amt_str = p.get('info', {}).get("positionAmt", "0") 
                try:
                    p_position_amt = float(p_position_amt_str)
                except ValueError:
                    p_position_amt = 0.0 # Handle cases where positionAmt might not be a valid number
                
                print(f"--- DEBUG Check: Comparing webhook symbol '{symbol}' with position symbol '{p_info_symbol}' and position amount '{p_position_amt_str}' (float: {p_position_amt}) ---")
                
                if p_info_symbol == symbol and p_position_amt != 0:
                    print(f"--- DEBUG Match Found! Position: {p} ---")
                    pos = p
                    break # Found the relevant position, exit loop
            
            if pos:
                qty_to_close = abs(float(pos.get('info', {}).get("positionAmt", 0))) # Also update this to use 'info'
                side_to_close = 'sell' if float(pos.get('info', {}).get("positionAmt")) > 0 else 'buy' # And this
                
                print(f"Open position found: {pos.get('info', {}).get('positionAmt')} {symbol}. Placing market {side_to_close.upper()} order for {qty_to_close} to close.")
                
                if side_to_close == 'sell':
                    order = exchange.create_market_sell_order(symbol, qty_to_close, {'reduceOnly': True})
                else: # side_to_close == 'buy'
                    order = exchange.create_market_buy_order(symbol, qty_to_close, {'reduceOnly': True})
                
                print(f"SUCCESS: Close Order executed.")
                return jsonify({"status": "success", "order": order}), 200
            else:
                print("Info: No open position found to close for this symbol.")
                return jsonify({"status": "info", "message": "No open position to close"}), 200
        else:
            return jsonify({"status": "error", "message": "Invalid side/action"}), 400

    except ccxt.BaseError as e:
        print(f"ERROR (CCXT): An error occurred with the exchange: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        print(f"ERROR (General): An unexpected error occurred: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
