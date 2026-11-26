"""Apply the directory schema explicitly; never migrate the legacy database."""
from pathlib import Path
import os
import psycopg
from dotenv import load_dotenv

def main():
    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"],connect_timeout=10,prepare_threshold=None,sslmode="require",autocommit=True) as conn:
        conn.execute(Path(__file__).resolve().parents[1].joinpath("sql/workspace_directory.sql").read_text(encoding="utf-8"))
        rows=conn.execute("SELECT relname,relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='flagguard_private' AND relname IN ('workspaces','members') ORDER BY relname").fetchall()
        if rows!=[("members",True),("workspaces",True)]:
            raise RuntimeError("Workspace schema verification failed")
        print("Workspace directory initialized; RLS enabled on both tables.")

if __name__=="__main__":
    main()
