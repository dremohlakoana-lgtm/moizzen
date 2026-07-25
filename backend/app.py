import os, sys
# Make sure backend folder is in path so 'database' module is found
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from flask import Flask, request, jsonify, send_from_directory
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_cors import CORS
import bcrypt, uuid, json
from datetime import datetime, timedelta
from database import conn, init
import yfinance as yf
FRONTEND_DIR = os.path.join(BASE_DIR, 'frontend')
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET", "moizzen-secret-key-2024-change-in-prod")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)
CORS(app)
jwt = JWTManager(app)

# ── Helpers ────────────────────────────────────────────────────────────────────
def make_ref():
    return "MZN" + uuid.uuid4().hex[:10].upper()

def user_by_id(uid):
    db = conn(); c = db.cursor()
    c.execute("SELECT * FROM users WHERE id=?", (uid,))
    row = c.fetchone(); db.close()
    return dict(row) if row else None

def get_balance(uid):
    db = conn(); c = db.cursor()
    c.execute("SELECT balance, currency FROM wallets WHERE user_id=?", (uid,))
    row = c.fetchone(); db.close()
    return dict(row) if row else {"balance": 0, "currency": "ZAR"}

def update_balance(uid, amount, db=None):
    close = False
    if db is None: db = conn(); close = True
    db.execute("UPDATE wallets SET balance=balance+?, updated_at=? WHERE user_id=?",
               (amount, datetime.now().isoformat(), uid))
    if close: db.commit(); db.close()

# ── Auth ───────────────────────────────────────────────────────────────────────
@app.route("/api/auth/register", methods=["POST"])
def register():
    d = request.json
    full_name = d.get("full_name","").strip()
    email     = d.get("email","").strip().lower()
    phone     = d.get("phone","").strip()
    password  = d.get("password","")
    country   = d.get("country","ZA")
    currency  = d.get("currency","ZAR")

    if not all([full_name, email, password]):
        return jsonify({"error": "Full name, email and password required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    db = conn(); c = db.cursor()
    try:
        c.execute("""INSERT INTO users (full_name,email,phone,password_hash,country,currency)
                     VALUES (?,?,?,?,?,?)""", (full_name,email,phone or None,hashed,country,currency))
        uid = c.lastrowid
        c.execute("INSERT INTO wallets (user_id,currency) VALUES (?,?)", (uid, currency))
        # Welcome bonus
        bonus = 100.0
        c.execute("""INSERT INTO transactions (ref,to_user,amount,currency,type,description)
                     VALUES (?,?,?,?,?,?)""",
                  (make_ref(), uid, bonus, currency, "bonus", "Welcome bonus from Moizzen 🎉"))
        db.execute("UPDATE wallets SET balance=? WHERE user_id=?", (bonus, uid))
        db.commit()
        token = create_access_token(identity=str(uid))
        return jsonify({"token": token, "user_id": uid, "message": "Account created! R100 welcome bonus added 🎉"}), 201
    except Exception as e:
        db.rollback()
        if "UNIQUE" in str(e): return jsonify({"error": "Email or phone already registered"}), 409
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/auth/login", methods=["POST"])
def login():
    d = request.json
    email    = d.get("email","").strip().lower()
    password = d.get("password","")
    db = conn(); c = db.cursor()
    c.execute("SELECT * FROM users WHERE email=? AND is_active=1", (email,))
    user = c.fetchone(); db.close()
    if not user:
        return jsonify({"error": "Invalid email or password"}), 401
    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return jsonify({"error": "Invalid email or password"}), 401
    token = create_access_token(identity=str(user["id"]))
    return jsonify({"token": token, "user_id": user["id"], "full_name": user["full_name"]})

# ── User Profile ───────────────────────────────────────────────────────────────
@app.route("/api/user/me", methods=["GET"])
@jwt_required()
def me():
    uid  = int(get_jwt_identity())
    user = user_by_id(uid)
    if not user: return jsonify({"error": "Not found"}), 404
    bal  = get_balance(uid)
    user.pop("password_hash", None)
    user["balance"]  = bal["balance"]
    user["currency"] = bal["currency"]
    return jsonify(user)

@app.route("/api/user/update", methods=["PUT"])
@jwt_required()
def update_profile():
    uid = int(get_jwt_identity())
    d   = request.json
    db  = conn()
    db.execute("UPDATE users SET full_name=?, phone=?, country=? WHERE id=?",
               (d.get("full_name"), d.get("phone"), d.get("country"), uid))
    db.commit(); db.close()
    return jsonify({"message": "Profile updated"})

# ── Wallet ─────────────────────────────────────────────────────────────────────
@app.route("/api/wallet/balance", methods=["GET"])
@jwt_required()
def balance():
    uid = int(get_jwt_identity())
    return jsonify(get_balance(uid))

@app.route("/api/wallet/deposit", methods=["POST"])
@jwt_required()
def deposit():
    uid = int(get_jwt_identity())
    d   = request.json
    amount   = float(d.get("amount", 0))
    method   = d.get("method", "card")
    currency = d.get("currency", "ZAR")
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than 0"}), 400
    db  = conn()
    ref = make_ref()
    db.execute("""INSERT INTO transactions (ref,to_user,amount,currency,type,description)
                  VALUES (?,?,?,?,?,?)""",
               (ref, uid, amount, currency, "deposit", f"Deposit via {method}"))
    update_balance(uid, amount, db)
    db.commit(); db.close()
    return jsonify({"message": f"R{amount:.2f} deposited successfully!", "ref": ref, "balance": get_balance(uid)["balance"]})

@app.route("/api/wallet/send", methods=["POST"])
@jwt_required()
def send_money():
    uid = int(get_jwt_identity())
    d   = request.json
    amount    = float(d.get("amount", 0))
    recipient = d.get("recipient", "").strip().lower()
    note      = d.get("note", "")

    if amount <= 0:
        return jsonify({"error": "Amount must be greater than 0"}), 400

    bal = get_balance(uid)
    if bal["balance"] < amount:
        return jsonify({"error": "Insufficient balance"}), 400

    db = conn(); c = db.cursor()
    c.execute("SELECT id, full_name FROM users WHERE email=? OR phone=?", (recipient, recipient))
    recv = c.fetchone()
    if not recv:
        db.close()
        return jsonify({"error": "Recipient not found. Check email or phone."}), 404

    if recv["id"] == uid:
        db.close()
        return jsonify({"error": "Cannot send to yourself"}), 400

    ref = make_ref()
    c.execute("""INSERT INTO transactions (ref,from_user,to_user,amount,currency,type,description)
                 VALUES (?,?,?,?,?,?,?)""",
              (ref, uid, recv["id"], amount, bal["currency"], "transfer",
               note or f"Transfer to {recv['full_name']}"))
    db.execute("UPDATE wallets SET balance=balance-?, updated_at=? WHERE user_id=?",
               (amount, datetime.now().isoformat(), uid))
    db.execute("UPDATE wallets SET balance=balance+?, updated_at=? WHERE user_id=?",
               (amount, datetime.now().isoformat(), recv["id"]))
    db.commit(); db.close()
    return jsonify({"message": f"R{amount:.2f} sent to {recv['full_name']}!", "ref": ref})

@app.route("/api/wallet/transactions", methods=["GET"])
@jwt_required()
def transactions():
    uid   = int(get_jwt_identity())
    limit = int(request.args.get("limit", 20))
    db = conn(); c = db.cursor()
    c.execute("""SELECT t.*, 
                   fu.full_name as from_name, 
                   tu.full_name as to_name
                FROM transactions t
                LEFT JOIN users fu ON t.from_user=fu.id
                LEFT JOIN users tu ON t.to_user=tu.id
                WHERE t.from_user=? OR t.to_user=?
                ORDER BY t.created_at DESC LIMIT ?""", (uid, uid, limit))
    rows = [dict(r) for r in c.fetchall()]
    db.close()
    # Label direction
    for r in rows:
        r["direction"] = "credit" if r["to_user"] == uid else "debit"
    return jsonify(rows)

@app.route("/api/wallet/request", methods=["POST"])
@jwt_required()
def request_money():
    uid = int(get_jwt_identity())
    d   = request.json
    amount = float(d.get("amount", 0))
    from_  = d.get("from_email", "").strip().lower()
    note   = d.get("note", "")
    user   = user_by_id(uid)
    return jsonify({
        "message": f"Payment request of R{amount:.2f} sent to {from_}",
        "request_link": f"moizzen://pay/{user['email']}?amount={amount}&note={note}"
    })

# ── Stocks ─────────────────────────────────────────────────────────────────────
POPULAR_STOCKS = [
    {"symbol":"AAPL","name":"Apple"},{"symbol":"TSLA","name":"Tesla"},
    {"symbol":"GOOGL","name":"Alphabet"},{"symbol":"MSFT","name":"Microsoft"},
    {"symbol":"AMZN","name":"Amazon"},{"symbol":"META","name":"Meta"},
    {"symbol":"NVDA","name":"NVIDIA"},{"symbol":"BTC-USD","name":"Bitcoin"},
    {"symbol":"ETH-USD","name":"Ethereum"},{"symbol":"SOL-USD","name":"Solana"},
    {"symbol":"NPN.JO","name":"Naspers"},{"symbol":"SOL.JO","name":"Sasol"},
    {"symbol":"MTN.JO","name":"MTN Group"},{"symbol":"SBK.JO","name":"Standard Bank"},
    {"symbol":"ABG.JO","name":"Absa Group"}
]

@app.route("/api/stocks/market", methods=["GET"])
@jwt_required()
def market():
    results = []
    symbols = [s["symbol"] for s in POPULAR_STOCKS[:10]]
    try:
        data = yf.download(symbols, period="2d", interval="1d", progress=False, auto_adjust=True)
        closes = data["Close"]
        for s in POPULAR_STOCKS[:10]:
            sym = s["symbol"]
            try:
                prices = closes[sym].dropna().tolist()
                curr   = prices[-1] if prices else 0
                prev   = prices[-2] if len(prices)>1 else curr
                chg    = ((curr-prev)/prev*100) if prev else 0
                results.append({
                    "symbol": sym, "name": s["name"],
                    "price": round(curr,2), "change_pct": round(chg,2),
                    "change": round(curr-prev,2)
                })
            except: pass
    except Exception as e:
        # Fallback static data if API fails
        results = [{"symbol":s["symbol"],"name":s["name"],"price":0,"change_pct":0,"change":0} for s in POPULAR_STOCKS[:10]]
    return jsonify(results)

@app.route("/api/stocks/quote/<symbol>", methods=["GET"])
@jwt_required()
def quote(symbol):
    try:
        tk   = yf.Ticker(symbol)
        info = tk.info
        hist = tk.history(period="30d")
        prices = hist["Close"].tolist()
        dates  = [str(d.date()) for d in hist.index.tolist()]
        return jsonify({
            "symbol":      symbol,
            "name":        info.get("longName", symbol),
            "price":       info.get("currentPrice") or info.get("regularMarketPrice", 0),
            "change_pct":  round(info.get("regularMarketChangePercent",0)*100 if info.get("regularMarketChangePercent",0)<1 else info.get("regularMarketChangePercent",0),2),
            "high":        info.get("dayHigh",0),
            "low":         info.get("dayLow",0),
            "volume":      info.get("volume",0),
            "market_cap":  info.get("marketCap",0),
            "pe_ratio":    info.get("trailingPE",0),
            "history":     prices,
            "dates":       dates
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stocks/portfolio", methods=["GET"])
@jwt_required()
def portfolio():
    uid = int(get_jwt_identity())
    db  = conn(); c = db.cursor()
    c.execute("SELECT * FROM stock_portfolio WHERE user_id=? AND shares>0", (uid,))
    rows = [dict(r) for r in c.fetchall()]
    db.close()
    total_value = 0
    enriched = []
    for r in rows:
        try:
            tk    = yf.Ticker(r["symbol"])
            price = tk.fast_info.last_price or r["avg_price"]
            value = price * r["shares"]
            pnl   = (price - r["avg_price"]) * r["shares"]
            total_value += value
            enriched.append({**r, "current_price": round(price,2),
                              "value": round(value,2), "pnl": round(pnl,2)})
        except:
            enriched.append({**r, "current_price": r["avg_price"],
                              "value": r["avg_price"]*r["shares"], "pnl": 0})
    return jsonify({"holdings": enriched, "total_value": round(total_value,2)})

@app.route("/api/stocks/buy", methods=["POST"])
@jwt_required()
def buy_stock():
    uid = int(get_jwt_identity())
    d   = request.json
    symbol = d.get("symbol","").upper()
    shares = float(d.get("shares", 0))
    if shares <= 0: return jsonify({"error": "Invalid shares amount"}), 400
    try:
        tk    = yf.Ticker(symbol)
        price = tk.fast_info.last_price
        if not price: return jsonify({"error": "Could not fetch price"}), 400
        total = round(price * shares, 2)
        bal   = get_balance(uid)
        if bal["balance"] < total:
            return jsonify({"error": f"Insufficient balance. Need R{total:.2f}, have R{bal['balance']:.2f}"}), 400
        db = conn(); c = db.cursor()
        # Deduct balance
        db.execute("UPDATE wallets SET balance=balance-? WHERE user_id=?", (total, uid))
        # Update portfolio
        c.execute("SELECT * FROM stock_portfolio WHERE user_id=? AND symbol=?", (uid, symbol))
        existing = c.fetchone()
        if existing:
            new_shares = existing["shares"] + shares
            new_avg    = ((existing["avg_price"]*existing["shares"]) + total) / new_shares
            db.execute("UPDATE stock_portfolio SET shares=?,avg_price=?,updated_at=? WHERE user_id=? AND symbol=?",
                       (new_shares, new_avg, datetime.now().isoformat(), uid, symbol))
        else:
            db.execute("INSERT INTO stock_portfolio (user_id,symbol,shares,avg_price) VALUES (?,?,?,?)",
                       (uid, symbol, shares, price))
        # Record order
        c.execute("INSERT INTO stock_orders (user_id,symbol,order_type,shares,price,total) VALUES (?,?,?,?,?,?)",
                  (uid, symbol, "buy", shares, price, total))
        # Transaction record
        ref = make_ref()
        c.execute("""INSERT INTO transactions (ref,from_user,amount,currency,type,description)
                     VALUES (?,?,?,?,?,?)""",
                  (ref, uid, total, bal["currency"], "stock_buy", f"Bought {shares} × {symbol} @ R{price:.2f}"))
        db.commit(); db.close()
        return jsonify({"message": f"Bought {shares} shares of {symbol} for R{total:.2f}!", "ref": ref})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stocks/sell", methods=["POST"])
@jwt_required()
def sell_stock():
    uid = int(get_jwt_identity())
    d   = request.json
    symbol = d.get("symbol","").upper()
    shares = float(d.get("shares", 0))
    db = conn(); c = db.cursor()
    c.execute("SELECT * FROM stock_portfolio WHERE user_id=? AND symbol=?", (uid, symbol))
    holding = c.fetchone()
    if not holding or holding["shares"] < shares:
        db.close()
        return jsonify({"error": "Insufficient shares"}), 400
    try:
        tk    = yf.Ticker(symbol)
        price = tk.fast_info.last_price
        total = round(price * shares, 2)
        new_shares = holding["shares"] - shares
        if new_shares <= 0:
            db.execute("DELETE FROM stock_portfolio WHERE user_id=? AND symbol=?", (uid, symbol))
        else:
            db.execute("UPDATE stock_portfolio SET shares=?,updated_at=? WHERE user_id=? AND symbol=?",
                       (new_shares, datetime.now().isoformat(), uid, symbol))
        db.execute("UPDATE wallets SET balance=balance+? WHERE user_id=?", (total, uid))
        ref = make_ref()
        c.execute("INSERT INTO stock_orders (user_id,symbol,order_type,shares,price,total) VALUES (?,?,?,?,?,?)",
                  (uid, symbol, "sell", shares, price, total))
        c.execute("""INSERT INTO transactions (ref,to_user,amount,currency,type,description)
                     VALUES (?,?,?,?,?,?)""",
                  (ref, uid, total, "ZAR", "stock_sell", f"Sold {shares} × {symbol} @ R{price:.2f}"))
        db.commit(); db.close()
        return jsonify({"message": f"Sold {shares} shares of {symbol} for R{total:.2f}!", "ref": ref})
    except Exception as e:
        db.close()
        return jsonify({"error": str(e)}), 500

@app.route("/api/stocks/orders", methods=["GET"])
@jwt_required()
def orders():
    uid = int(get_jwt_identity())
    db  = conn(); c = db.cursor()
    c.execute("SELECT * FROM stock_orders WHERE user_id=? ORDER BY created_at DESC LIMIT 30", (uid,))
    rows = [dict(r) for r in c.fetchall()]; db.close()
    return jsonify(rows)

# ── Cards ──────────────────────────────────────────────────────────────────────
@app.route("/api/cards", methods=["GET"])
@jwt_required()
def get_cards():
    uid = int(get_jwt_identity())
    db  = conn(); c = db.cursor()
    c.execute("SELECT * FROM cards WHERE user_id=?", (uid,))
    rows = [dict(r) for r in c.fetchall()]; db.close()
    return jsonify(rows)

@app.route("/api/cards/issue", methods=["POST"])
@jwt_required()
def issue_card():
    uid  = int(get_jwt_identity())
    user = user_by_id(uid)
    import random
    number    = " ".join(["".join([str(random.randint(0,9)) for _ in range(4)]) for _ in range(4)])
    last_four = number[-4:]
    expiry    = f"{datetime.now().month:02d}/{(datetime.now().year+3)%100:02d}"
    db = conn()
    db.execute("INSERT INTO cards (user_id,card_number,last_four,expiry,card_type) VALUES (?,?,?,?,?)",
               (uid, number, last_four, expiry, "virtual"))
    db.commit(); db.close()
    return jsonify({"message": "Virtual card issued!", "last_four": last_four, "expiry": expiry})

# ── KYC ───────────────────────────────────────────────────────────────────────
@app.route("/api/kyc/submit", methods=["POST"])
@jwt_required()
def kyc_submit():
    uid = int(get_jwt_identity())
    d   = request.json
    db  = conn()
    db.execute("INSERT OR REPLACE INTO kyc_docs (user_id,doc_type,doc_number,status) VALUES (?,?,?,?)",
               (uid, d.get("doc_type"), d.get("doc_number"), "pending"))
    db.execute("UPDATE users SET kyc_status='submitted' WHERE id=?", (uid,))
    db.commit(); db.close()
    return jsonify({"message": "KYC documents submitted. Verification within 24 hours."})

# ── Admin ─────────────────────────────────────────────────────────────────────
@app.route("/api/admin/stats", methods=["GET"])
@jwt_required()
def admin_stats():
    uid  = int(get_jwt_identity())
    user = user_by_id(uid)
    if not user or not user["is_admin"]:
        return jsonify({"error": "Unauthorized"}), 403
    db = conn(); c = db.cursor()
    c.execute("SELECT COUNT(*) as n FROM users"); total_users = c.fetchone()["n"]
    c.execute("SELECT SUM(balance) as n FROM wallets"); total_bal = c.fetchone()["n"] or 0
    c.execute("SELECT COUNT(*) as n FROM transactions"); total_tx = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) as n FROM stock_orders"); total_orders = c.fetchone()["n"]
    db.close()
    return jsonify({"total_users": total_users,"total_balance": total_bal,
                    "total_transactions": total_tx,"total_orders": total_orders})

@app.route("/api/admin/users", methods=["GET"])
@jwt_required()
def admin_users():
    uid  = int(get_jwt_identity())
    user = user_by_id(uid)
    if not user or not user["is_admin"]:
        return jsonify({"error": "Unauthorized"}), 403
    db = conn(); c = db.cursor()
    c.execute("""SELECT u.id,u.full_name,u.email,u.phone,u.country,u.kyc_status,
                        u.is_active,u.created_at,w.balance
                 FROM users u LEFT JOIN wallets w ON u.id=w.user_id
                 ORDER BY u.created_at DESC""")
    rows = [dict(r) for r in c.fetchall()]; db.close()
    return jsonify(rows)

# ── Currency rates (free) ─────────────────────────────────────────────────────
@app.route("/api/rates", methods=["GET"])
@jwt_required()
def rates():
    try:
        import requests as req
        r = req.get("https://open.er-api.com/v6/latest/ZAR", timeout=5)
        data = r.json()
        return jsonify({"base": "ZAR", "rates": data.get("rates", {})})
    except:
        return jsonify({"base": "ZAR", "rates": {"USD":0.055,"EUR":0.051,"GBP":0.044,"NGN":43.2,"GHS":0.78}})

# ── Serve frontend ─────────────────────────────────────────────────────────────
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    print("🏦 Moizzen Banking API starting...")
    app.run(host="0.0.0.0", port=5000, debug=False)

# ── Admin Setup (first time only) ─────────────────────────────────────────────
@app.route("/api/admin/setup", methods=["POST"])
def admin_setup():
    """Make a user admin - use once to set up your first admin"""
    d      = request.json
    secret = d.get("setup_secret","")
    email  = d.get("email","")
    if secret != os.environ.get("ADMIN_SETUP_SECRET","moizzen-admin-2024"):
        return jsonify({"error": "Wrong secret"}), 403
    db = conn(); c = db.cursor()
    c.execute("UPDATE users SET is_admin=1 WHERE email=?", (email,))
    db.commit(); db.close()
    return jsonify({"message": f"✅ {email} is now admin!"})
