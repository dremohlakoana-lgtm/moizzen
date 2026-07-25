import sqlite3, os
from datetime import datetime

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moizzen.db")

def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    db = conn()
    c  = db.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name     TEXT NOT NULL,
        email         TEXT UNIQUE NOT NULL,
        phone         TEXT UNIQUE,
        password_hash TEXT NOT NULL,
        country       TEXT DEFAULT 'ZA',
        currency      TEXT DEFAULT 'ZAR',
        avatar        TEXT DEFAULT '',
        kyc_status    TEXT DEFAULT 'pending',
        is_active     INTEGER DEFAULT 1,
        is_admin      INTEGER DEFAULT 0,
        created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS wallets (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER UNIQUE NOT NULL,
        balance    REAL DEFAULT 0.0,
        currency   TEXT DEFAULT 'ZAR',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ref         TEXT UNIQUE NOT NULL,
        from_user   INTEGER,
        to_user     INTEGER,
        amount      REAL NOT NULL,
        currency    TEXT DEFAULT 'ZAR',
        type        TEXT NOT NULL,
        status      TEXT DEFAULT 'completed',
        description TEXT,
        meta        TEXT DEFAULT '{}',
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(from_user) REFERENCES users(id),
        FOREIGN KEY(to_user)   REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stock_portfolio (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        symbol     TEXT NOT NULL,
        shares     REAL DEFAULT 0,
        avg_price  REAL DEFAULT 0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, symbol),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stock_orders (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        symbol     TEXT NOT NULL,
        order_type TEXT NOT NULL,
        shares     REAL NOT NULL,
        price      REAL NOT NULL,
        total      REAL NOT NULL,
        status     TEXT DEFAULT 'filled',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS cards (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        card_number TEXT NOT NULL,
        card_type   TEXT DEFAULT 'virtual',
        last_four   TEXT NOT NULL,
        expiry      TEXT NOT NULL,
        is_active   INTEGER DEFAULT 1,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS kyc_docs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        doc_type    TEXT NOT NULL,
        doc_number  TEXT,
        status      TEXT DEFAULT 'pending',
        submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    db.commit()
    db.close()

init()
