import random
from datetime import datetime, timedelta
import faker
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_test_data(cursor):
    fake = faker.Faker()

    # Constants for data generation
    TOTAL_USERS = 1000
    TOTAL_MOVIES = 200
    MOVIES_PER_USER_RANGE = (5, 20)
    GENRES = ['Action', 'Comedy', 'Drama', 'Horror', 'Sci-Fi', 'Romance', 'Documentary', 'Thriller']
    PLAN_TYPES = ['Basic', 'Standard', 'Premium']
    COUNTRIES = ['USA', 'Canada', 'UK', 'France', 'Germany', 'Japan', 'Australia', 'Brazil']

    # Generate Users
    logger.info("Generating users...")
    user_data = []
    for _ in range(TOTAL_USERS):
        signup_date = fake.date_between(start_date='-3y', end_date='today')
        user = (
            fake.name(),
            fake.email(),
            signup_date,
            random.choice(COUNTRIES)
        )
        cursor.execute("""
            INSERT INTO users (name, email, signup_date, country)
            VALUES (%s, %s, %s, %s) RETURNING user_id
        """, user)
        user_id = cursor.fetchone()[0]
        user_data.append((user_id, signup_date))

    # Generate Subscriptions
    logger.info("Generating subscriptions...")
    for user_id, signup_date in user_data:
        status = random.choices(['active', 'cancelled', 'paused'], weights=[0.8, 0.15, 0.05])[0]
        renewal_date = datetime.now().date() + timedelta(days=random.randint(1, 365))
        if status == 'cancelled':
            renewal_date = fake.date_between(start_date=signup_date, end_date='today')

        cursor.execute("""
            INSERT INTO subscriptions (user_id, plan_type, status, renewal_date)
            VALUES (%s, %s, %s, %s)
        """, (user_id, random.choice(PLAN_TYPES), status, renewal_date))

    # Generate Movies
    logger.info("Generating movies...")
    movie_data = []
    for _ in range(TOTAL_MOVIES):
        movie = (
            fake.catch_phrase(),  # as movie title
            random.choice(GENRES),
            random.randint(1990, 2024),
            round(random.uniform(1.0, 10.0), 1)  # rating between 1.0 and 10.0
        )
        cursor.execute("""
            INSERT INTO movies (title, genre, release_year, rating)
            VALUES (%s, %s, %s, %s) RETURNING movie_id
        """, movie)
        movie_data.append(cursor.fetchone()[0])

    # Generate Viewing History
    logger.info("Generating viewing history...")
    for user_id, signup_date in user_data:
        num_movies = random.randint(*MOVIES_PER_USER_RANGE)
        watched_movies = random.sample(movie_data, num_movies)

        for movie_id in watched_movies:
            watch_date = fake.date_time_between(
                start_date=signup_date,
                end_date='now'
            )
            duration = random.randint(10, 180)

            cursor.execute("""
                INSERT INTO viewing_history (user_id, movie_id, watch_time, duration_watched)
                VALUES (%s, %s, %s, %s)
            """, (user_id, movie_id, watch_date, duration))


def verify_data(cursor):
    """Verify the number of records in each table"""
    tables = ['users', 'subscriptions', 'movies', 'viewing_history']
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        logger.info(f"{table}: {count} records")


def setup_database(conn):
    """Initialize database schema"""
    with conn.cursor() as cursor:
        # Create tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY,
                name VARCHAR(50),
                email VARCHAR(100),
                signup_date DATE,
                country VARCHAR(50)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                subscription_id SERIAL PRIMARY KEY,
                user_id INT REFERENCES users(user_id),
                plan_type VARCHAR(20),
                status VARCHAR(20),
                renewal_date DATE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                movie_id SERIAL PRIMARY KEY,
                title VARCHAR(100),
                genre VARCHAR(50),
                release_year INT,
                rating DECIMAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS viewing_history (
                history_id SERIAL PRIMARY KEY,
                user_id INT REFERENCES users(user_id),
                movie_id INT REFERENCES movies(movie_id),
                watch_time TIMESTAMP,
                duration_watched INT
            )
        """)


def populate_database(conn):
    """Populate database with test data"""
    with conn.cursor() as cursor:
        generate_test_data(cursor)
        conn.commit()
        logger.info("\nVerifying data counts:")
        verify_data(cursor)


if __name__ == "__main__":
    # This allows the script to be run independently for data generation only
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:15") as postgres:
        conn = psycopg2.connect(
            host=postgres.get_container_host_ip(),
            port=postgres.get_exposed_port(5432),
            dbname="test",
            user="test",
            password="test"
        )
        setup_database(conn)
        populate_database(conn)
        conn.close()