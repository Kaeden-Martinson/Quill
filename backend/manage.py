"""Admin commands, run on the laptop itself (never exposed over the web).

    python backend/manage.py users
    python backend/manage.py remove NAME          # deletes the account and all their drafts
    python backend/manage.py reset-password NAME  # prints a temporary password
    python backend/manage.py signout-all          # ends every session everywhere
    python backend/manage.py backup               # copies the database to data/backups/ (keeps 14)
"""
import secrets
import shutil
import sqlite3
import sys
from datetime import datetime

import db
import security
from config import DATA_DIR, DB_PATH


def users(conn):
    rows = conn.execute(
        "SELECT u.name, u.created, "
        "(SELECT COUNT(*) FROM drafts d WHERE d.user_id = u.id) AS drafts, "
        "(SELECT MAX(created) FROM sessions s WHERE s.user_id = u.id) AS last_login "
        "FROM users u ORDER BY u.created"
    ).fetchall()
    fmt = lambda ts: datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "never"
    for r in rows:
        print(f"{r['name']:<24} joined {fmt(r['created'])}  last sign-in {fmt(r['last_login'])}  {r['drafts']} drafts")
    if not rows:
        print("No users yet.")


def find(conn, name):
    row = conn.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
    if not row:
        sys.exit(f"No user named {name!r}.")
    return row["id"]


def remove(conn, name):
    uid = find(conn, name)
    if input(f"Delete {name} and ALL their drafts and history? Type the name to confirm: ") != name:
        sys.exit("Cancelled.")
    conn.execute("DELETE FROM versions WHERE draft_id IN (SELECT id FROM drafts WHERE user_id = ?)", (uid,))
    for table in ("drafts", "profiles", "feedback", "sessions"):
        conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    print(f"Removed {name}.")


def reset_password(conn, name):
    uid = find(conn, name)
    temp = secrets.token_urlsafe(9)
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (security.hash_password(temp), uid))
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
    print(f"Temporary password for {name}: {temp}")


def signout_all(conn):
    conn.execute("DELETE FROM sessions")
    print("Everyone has been signed out.")


KEEP_BACKUPS = 14


def backup(_conn):
    dest_dir = DATA_DIR / "backups"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / f"quill-{datetime.now():%Y%m%d-%H%M%S}.db"
    # SQLite's backup API copies safely even while the server is running.
    src, out = sqlite3.connect(DB_PATH), sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        src.close()
        out.close()
    print(f"Backed up to {dest}")
    for old in sorted(dest_dir.glob("quill-*.db"))[:-KEEP_BACKUPS]:
        old.unlink()
        print(f"Removed old backup {old.name}")


COMMANDS = {"users": users, "remove": remove, "reset-password": reset_password,
            "signout-all": signout_all, "backup": backup}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    db.init()
    with db.connect() as conn:
        if sys.argv[1] in ("remove", "reset-password"):
            if len(sys.argv) < 3:
                sys.exit(f"Usage: python backend/manage.py {sys.argv[1]} NAME")
            COMMANDS[sys.argv[1]](conn, sys.argv[2])
        else:
            COMMANDS[sys.argv[1]](conn)
