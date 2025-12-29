import os
import sys
import psycopg

def run_migration(sql_file_path):
    url = os.getenv("DATABASE_URL")
    if not url:
        print("Error: DATABASE_URL environment variable not set.")
        sys.exit(1)
        
    print(f"Connecting to {url.split('@')[1] if '@' in url else 'database'}...")
    
    try:
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
            
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                print(f"Executing {sql_file_path}...")
                cur.execute(sql_content)
                conn.commit()
                print("Migration executed successfully.")
                
    except Exception as e:
        print(f"Error executing migration: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_migration.py <path_to_sql_file>")
        sys.exit(1)
    
    run_migration(sys.argv[1])
