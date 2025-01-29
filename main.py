import os
import time
import random
import psycopg2
from datetime import datetime
import google.generativeai as genai
from testcontainers.postgres import PostgresContainer
from dataclasses import dataclass
from dotenv import load_dotenv
from typing import List, Optional
import re
from generate import setup_database, populate_database


@dataclass
class QueryMetrics:
    prompt: str
    sql_query: str
    execution_time: float
    retry_count: int
    success: bool
    error_type: Optional[str]
    rows_returned: int
    chaos_type: Optional[str]
    timestamp: datetime


class NetflixChaosRunner:
    def __init__(self):
        load_dotenv()
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        self.metrics: List[QueryMetrics] = []
        self.chaos_active = True

    def generate_sql_query(self, prompt: str) -> str:
        structured_prompt = f"""You are a SQL query generator for a Netflix-like database. 
        Respond ONLY with the exact PostgreSQL query, nothing else - no explanations, no markdown formatting, no code blocks.

        Schema:
        - users (user_id PRIMARY KEY, name, email, signup_date, country)
        - subscriptions (subscription_id PRIMARY KEY, user_id FOREIGN KEY, plan_type, status, renewal_date)
        - movies (movie_id PRIMARY KEY, title, genre, release_year, rating)
        - viewing_history (history_id PRIMARY KEY, user_id FOREIGN KEY, movie_id FOREIGN KEY, watch_time, duration_watched)

        Task: {prompt}
        """

        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(structured_prompt)

        clean_sql = response.text.strip()
        if clean_sql.startswith("```sql"):
            clean_sql = re.sub(r'^```sql\s*|\s*```$', '', clean_sql, flags=re.DOTALL)
        return clean_sql.strip()

    def simulate_db_specific_chaos(self, conn):
        if not self.chaos_active or random.random() > 0.3:
            return None

        chaos_types = {
            "long_query": "SELECT pg_sleep(2);",
            "timeout": "SET statement_timeout = '100ms';",
            "kill_connection": "SELECT pg_terminate_backend(pg_backend_pid());",
            "temp_table_stress": """
                CREATE TEMP TABLE stress_test AS 
                SELECT generate_series(1,50000) AS id;
                DROP TABLE stress_test;
            """
        }

        chaos_type = random.choice(list(chaos_types.keys()))
        print(f"🌪️ Simulating database chaos: {chaos_type}")

        try:
            with conn.cursor() as cur:
                cur.execute(chaos_types[chaos_type])
            conn.commit()
        except Exception as e:
            print(f"Chaos error (expected): {e}")

        return chaos_type

    def execute_query_with_retry(self, conn, sql_query: str, max_retries: int = 3):
        metrics = QueryMetrics(
            prompt="",
            sql_query=sql_query,
            execution_time=0,
            retry_count=0,
            success=False,
            error_type=None,
            rows_returned=0,
            chaos_type=None,
            timestamp=datetime.now()
        )

        start_time = time.time()

        for attempt in range(max_retries):
            try:
                db_chaos = self.simulate_db_specific_chaos(conn)
                if db_chaos:
                    metrics.chaos_type = db_chaos

                with conn.cursor() as cursor:
                    cursor.execute(sql_query)
                    results = cursor.fetchall()
                    conn.commit()

                    metrics.success = True
                    metrics.rows_returned = len(results)
                    metrics.retry_count = attempt
                    return metrics, results

            except psycopg2.Error as e:
                conn.rollback()
                metrics.error_type = str(e)
                metrics.retry_count = attempt + 1
                print(f"🔄 Retry {attempt + 1}/{max_retries}: {e}")
                time.sleep(random.uniform(0.1, 0.5) * (attempt + 1))

            finally:
                metrics.execution_time = time.time() - start_time

        return metrics, None

    def analyze_metrics(self):
        """Analyze the collected metrics"""
        total_queries = len(self.metrics)
        successful_queries = sum(1 for m in self.metrics if m.success)
        avg_execution_time = sum(m.execution_time for m in self.metrics) / total_queries
        chaos_incidents = sum(1 for m in self.metrics if m.chaos_type is not None)

        return {
            "Total Queries": total_queries,
            "Success Rate": f"{(successful_queries / total_queries) * 100:.2f}%",
            "Average Execution Time": f"{avg_execution_time:.3f}s",
            "Chaos Incidents": chaos_incidents
        }

    def run_resilience_test(self):
        with PostgresContainer("postgres:15") as postgres:
            db_params = {
                "host": postgres.get_container_host_ip(),
                "port": postgres.get_exposed_port(5432),
                "dbname": "test",
                "user": "test",
                "password": "test"
            }

            print("🚀 Starting Netflix-style database resilience test...")

            conn = psycopg2.connect(**db_params)

            # Initialize and populate database
            print("Setting up database schema...")
            setup_database(conn)
            print("Populating database with test data...")
            populate_database(conn)

            test_prompts = [
                "Find the top 5 most-watched movies in the last month",
                "List users who watched more than 10 movies last month",
                "Get users who have never finished a movie",
                "Find churn risk users (users inactive for last 60 days)",
                "Calculate the average watch time per genre",
                "Find the most-watched genre in each country",
                "Find users who have watched all movies of a particular genre"
            ]

            for prompt in test_prompts:
                print(f"\n{'=' * 50}")
                print(f"📝 Testing prompt: {prompt}")

                sql_query = self.generate_sql_query(prompt)
                print(f"🔍 Generated SQL: {sql_query}")

                metrics, results = self.execute_query_with_retry(conn, sql_query)
                metrics.prompt = prompt
                self.metrics.append(metrics)

                if results is not None:
                    print(f"✅ Query successful ({len(results)} rows)")
                    print("Sample results:")
                    for row in results[:3]:
                        print(row)
                else:
                    print("❌ Query failed after all retries")

            print("\n📊 Test Results Summary:")
            analysis = self.analyze_metrics()
            for key, value in analysis.items():
                print(f"{key}: {value}")

            conn.close()


if __name__ == "__main__":
    runner = NetflixChaosRunner()
    runner.run_resilience_test()