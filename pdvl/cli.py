from __future__ import annotations
import argparse
import os
from pathlib import Path
import sqlite3
from .config import home
from .db import init_db, db_path


def main():
    p = argparse.ArgumentParser(prog="pdvl", description="PDVL Studio research workbench")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("serve")
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    sub.add_parser("backup")
    sub.add_parser("mcp")
    args = p.parse_args()
    if args.cmd == "init":
        init_db()
        print(f"PDVL database ready at {db_path()}")
    elif args.cmd == "serve":
        import uvicorn
        init_db()
        host = os.getenv("PDVL_HOST", "127.0.0.1")
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise SystemExit("Refusing public binding: local-first service has no authentication")
        uvicorn.run("pdvl.api:app", host=host, port=int(os.getenv("PDVL_PORT", "8765")))
    elif args.cmd == "worker":
        from .worker import process_one, serve_worker
        init_db()
        if args.once:
            print(process_one() or "No queued jobs")
        else:
            serve_worker()
    elif args.cmd == "backup":
        init_db()
        target = home() / f"pdvl-backup.sqlite3"
        src = sqlite3.connect(db_path())
        dst = sqlite3.connect(target)
        try: src.backup(dst)
        finally: src.close(); dst.close()
        print(f"Backup saved: {target}")
    elif args.cmd == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main()

if __name__ == "__main__":
    main()
