from flask import Flask, request, jsonify
import os
import ccxt

app = Flask(__name__)

# --- Load Environment Variables ---
# These must be set in your Render dashboard Environment section
# Use the API keys you generate from the Binance Testnet website
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
SECRET_KEY = os.getenv("SECRET_KEY", "test1234")  # Should match your TradingView alert's secret

# --- Check for API Keys ---
if not API_KEY or not API_SECRET:
    raise Exception("CRITICAL: Missing API_KEY or API_SECRET in environment variables. Please check your Render dashboard.")

# --- Initialize Exchange Connection for Binance Futures Testnet ---
try:
    print("Attempting to connect to Binance Futures Testnet...")
    
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',  # This is crucial for futures trading
        }
    })

    # This command tells CCXT to use the testnet servers instead of the live ones.
    exchange.set_sandbox_mode(True)

    # Load markets to confirm the connection is successful
    exchange.load_markets()
    print("SUCCESS: Connection to Binance Futures Testnet established.")

except Exception as e:
    raise Exception(f"Error initializing exchange connection: {e}")
# --- End of Connection Block ---


@app.route('/')
def home():
    """ A simple route to confirm the bot is online and running. """
    return "Webhook Bot for Binance Futures is live!"


@app.route('/webhook', methods=['POST'])
def webhook():
    """ This is the main endpoint that receives and processes alerts from TradingView. """
    try:
        data = request.get_json(force=True)
        print(f"Webhook received: {data}")
    except Exception as e:
        print(f"Error: Could not parse incoming JSON. Reason: {e}")
        return jsonify({"status": "error", "message": f"Invalid JSON: {e}"}), 400

    # 1. Validate the secret key to ensure the request is from a trusted source
    if data.get("secret") != SECRET_KEY:
        print(f"Error: Invalid secret key. Expected '{SECRET_KEY}', but received '{data.get('secret')}'.")
        return jsonify({"status": "error", "message": "Invalid secret key"}), 403

    # 2. Extract data from the webhook payload
    # Note: Binance uses symbols like 'ETHUSDT' (no hyphen)
    symbol = data.get("symbol")
    side = data.get("side")
    action = data.get("action")
    try:
        qty_pct = float(data.get("qty_pct", 0))
    except (ValueError, TypeError):
        qty_pct = 0 # Default to 0 if the value is invalid

    if not symbol:
        return jsonify({"status": "error", "message": "Missing 'symbol' in webhook data"}), 400

    # --- Trading Logic ---
    try:
        # 3. Handle a BUY (entry) signal
        if side == "buy":
            print(f"Processing BUY order for {symbol}...")
            
            # Fetch available balance (ensure you have testnet USDT)
            balance = exchange.fetch_balance()
            quote_currency = "USDT" 
            available_balance = balance['free'].get(quote_currency, 0)
            print(f"Available balance: {available_balance} {quote_currency}")

            if available_balance <= 1: # Check for a minimum balance to trade
                 return jsonify({"status": "error", "message": f"Insufficient balance. Only {available_balance} {quote_currency} available."}), 400

            # Calculate order size
            ticker = exchange.fetch_ticker(symbol)
            last_price = ticker['last']
            amount_in_usdt = available_balance * (qty_pct / 100)
            # For futures, we often use leverage. For this example, assuming 1x leverage.
            # Amount should be in the base currency (e.g., ETH) for the order.
            amount = amount_in_usdt / last_price
            
            print(f"Attempting to place a market BUY order for {amount:.4f} {symbol} at ~${last_price}")

            # Place the market buy order
            order = exchange.create_market_buy_order(symbol, amount)
            print(f"SUCCESS: Buy Order executed: {order}")
            return jsonify({"status": "success", "order": order}), 200

        # 4. Handle a CLOSE signal
        elif action == "close":
            print(f"Processing CLOSE signal for {symbol}...")
            
            # Fetch current positions
            positions = exchange.fetch_positions([symbol])
            
            # Find the open position for the specified symbol
            # Binance uses 'entryPrice' to identify a position
            pos = next((p for p in positions if p.get('symbol') == symbol and float(p.get("entryPrice", 0)) > 0), None)

            if pos and float(pos.get("contracts", 0)) > 0:
                qty = float(pos["contracts"])
                print(f"Open position found: {qty} {symbol}. Placing market SELL order to close.")
                
                # Create a market sell order with reduceOnly to ensure it only closes the position
                order = exchange.create_market_sell_order(symbol, qty, {"reduceOnly": True})
                
                print(f"SUCCESS: Close Order executed: {order}")
                return jsonify({"status": "success", "order": order}), 200
            else:
                print("Info: No open position found to close for this symbol.")
                return jsonify({"status": "info", "message": "No open position to close"}), 200

        else:
            return jsonify({"status": "error", "message": "Webhook received with invalid 'side' or 'action'"}), 400

    except ccxt.BaseError as e:
        # Catch CCXT-specific errors for clear logging
        print(f"ERROR (CCXT): An error occurred with the exchange: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        # Catch any other unexpected errors
        print(f"ERROR (General): An unexpected error occurred: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    # Get the port from Render's environment variable, defaulting to 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
