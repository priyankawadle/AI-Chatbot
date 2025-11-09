import psycopg2
from psycopg2 import OperationalError

def test_postgres_connection():
    try:
        # Connection details
        connection = psycopg2.connect(
            host="localhost",          # or "127.0.0.1"
            port="5432",
            database="supportbot",
            user="supportuser",
            password="Str0ngP@ss!2025"
        )

        print("✅ Connection to PostgreSQL successful!")

        # Create a cursor to test a simple query
        cursor = connection.cursor()
        cursor.execute("SELECT version();")
        db_version = cursor.fetchone()
        print(f"📦 PostgreSQL version: {db_version[0]}")

    except OperationalError as e:
        print("❌ Unable to connect to PostgreSQL!")
        print(f"Error: {e}")
    finally:
        if 'connection' in locals() and connection:
            cursor.close()
            connection.close()
            print("🔌 Connection closed.")

if __name__ == "__main__":
    test_postgres_connection()
