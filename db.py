import pymysql
import csv
from dotenv import load_dotenv
import os

load_dotenv()
db_password = os.getenv('DB_PASSWORD')

connection = pymysql.connect(
    host='localhost',
    user='root',
    password=db_password,
    database='cinema_bot',
    charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor
)


def import_countries(connection, csv_path):
    with connection.cursor() as cursor:
        with open(csv_path, encoding='cp1251') as file:
            reader = csv.reader(file, delimiter=';')
            next(reader)  # пропускаем заголовок
            for row in reader:
                name = row[1].strip()
                cursor.execute("INSERT INTO countries (name) VALUES (%s)", (name,))
    connection.commit()


def import_age_limits(connection, csv_path):
    with connection.cursor() as cursor:
        with open(csv_path, encoding='cp1251') as file:
            reader = csv.reader(file, delimiter=';')
            next(reader)
            for row in reader:
                label = row[1].strip()
                cursor.execute("INSERT INTO age_limits (label) VALUES (%s)", (label,))
    connection.commit()


def import_genres(connection, csv_path):
    with connection.cursor() as cursor:
        with open(csv_path, encoding='cp1251') as file:
            reader = csv.reader(file, delimiter=';')
            next(reader)
            for row in reader:
                name = row[1].strip()
                cursor.execute("INSERT INTO genres (name) VALUES (%s)", (name,))
    connection.commit()


def import_directors(connection, csv_path):
    with connection.cursor() as cursor:
        with open(csv_path, encoding='cp1251') as file:
            reader = csv.DictReader(file, delimiter=';')
            for row in reader:
                name = row['director_name'].strip()
                surname = row['director_surname'].strip()
                gender = row['gender'].strip()
                cursor.execute("""
                    INSERT INTO directors (name, surname, gender)
                    VALUES (%s, %s, %s)
                """, (name, surname, gender))
    connection.commit()


def import_actors(connection, csv_path):
    with connection.cursor() as cursor:
        with open(csv_path, encoding='cp1251') as file:
            reader = csv.DictReader(file, delimiter=';')
            for row in reader:
                name = row['actor_name'].strip()
                surname = row['actor_surname'].strip()
                gender = row['gender'].strip()
                cursor.execute("""
                    INSERT INTO actors (name, surname, gender)
                    VALUES (%s, %s, %s)
                """, (name, surname, gender))
    connection.commit()


def import_genre_films(connection, csv_path):
    with connection.cursor() as cursor:
        # Получаем максимальный ID фильма
        cursor.execute("SELECT MAX(id) AS max_id FROM films")
        max_film_id = cursor.fetchone()['max_id'] or 0

        with open(csv_path, encoding='cp1251') as file:
            reader = csv.reader(file, delimiter=';')
            next(reader)
            for row in reader:
                film_id = int(row[0])
                genre_id = int(row[1])

                if film_id > max_film_id:
                    print(f"❌ Пропущено: фильм {film_id} не существует (MAX = {max_film_id})")
                    continue

                cursor.execute("SELECT id FROM genres WHERE id = %s", (genre_id,))
                if not cursor.fetchone():
                    print(f"❌ Пропущено: жанр {genre_id} не найден.")
                    continue

                cursor.execute("""
                    SELECT 1 FROM genre_films WHERE id_film = %s AND id_genre = %s
                """, (film_id, genre_id))
                if cursor.fetchone():
                    print(f"⚠️ Пропущено: дубликат жанра {genre_id} для фильма {film_id}")
                    continue

                cursor.execute("""
                    INSERT INTO genre_films (id_film, id_genre)
                    VALUES (%s, %s)
                """, (film_id, genre_id))
    connection.commit()


def import_cast_films(connection, csv_path):
    with connection.cursor() as cursor:
        # Получаем максимальные ID
        cursor.execute("SELECT MAX(id) AS max_film_id FROM films")
        max_film_id = cursor.fetchone()['max_film_id'] or 0

        cursor.execute("SELECT MAX(id) AS max_actor_id FROM actors")
        max_actor_id = cursor.fetchone()['max_actor_id'] or 0

        with open(csv_path, encoding='cp1251') as file:
            reader = csv.reader(file, delimiter=';')
            next(reader)
            for row in reader:
                film_id = int(row[0])
                actor_id = int(row[1])

                if film_id > max_film_id:
                    print(f"❌ Пропущено: фильм {film_id} не найден (MAX = {max_film_id})")
                    continue

                if actor_id > max_actor_id:
                    print(f"❌ Пропущено: актёр {actor_id} не найден (MAX = {max_actor_id})")
                    continue

                cursor.execute("""
                    SELECT 1 FROM cast_films WHERE id_film = %s AND id_actor = %s
                """, (film_id, actor_id))
                if cursor.fetchone():
                    print(f"⚠️ Пропущено: дубликат актёра {actor_id} для фильма {film_id}")
                    continue

                cursor.execute("""
                    INSERT INTO cast_films (id_film, id_actor)
                    VALUES (%s, %s)
                """, (film_id, actor_id))
    connection.commit()


def import_films(connection, csv_path):
    with connection.cursor() as cursor:
        with open(csv_path, encoding='cp1251') as file:  # если у тебя CP1251 — поменяй обратно
            reader = csv.reader(file, delimiter=';')
            next(reader)
            for row in reader:
                name = row[1].strip()
                year = int(row[2])
                duration = int(row[3])
                rating = float(row[4].replace(',', '.'))

                id_director = int(row[5])
                id_country = int(row[6])
                id_age_limit = int(row[7])

                # Проверка всех внешних ключей
                cursor.execute("SELECT id FROM directors WHERE id = %s", (id_director,))
                if not cursor.fetchone():
                    print(f"❌ Пропущено: режиссер {id_director} не найден.")
                    continue

                cursor.execute("SELECT id FROM countries WHERE id = %s", (id_country,))
                if not cursor.fetchone():
                    print(f"❌ Пропущено: страна {id_country} не найдена.")
                    continue

                cursor.execute("SELECT id FROM age_limits WHERE id = %s", (id_age_limit,))
                if not cursor.fetchone():
                    print(f"❌ Пропущено: возрастное ограничение {id_age_limit} не найдено.")
                    continue

                # Вставка, если всё ок
                cursor.execute("""
                    INSERT INTO films (name, year, duration, rating, id_director, id_country, id_age_limit)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (name, year, duration, rating, id_director, id_country, id_age_limit))
    connection.commit()


def add_unique_constraint():
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                ALTER TABLE ratings
                ADD CONSTRAINT uniq_user_film UNIQUE (user_id, id_film);
            """)
        connection.commit()
        print("Ограничение UNIQUE успешно добавлено.")
    except pymysql.err.InternalError as e:
        print("Ошибка при добавлении ограничения:", e)
    finally:
        connection.close()

add_unique_constraint()


# import_countries(connection, 'C:/Users/Даша/Desktop/Учеба/2 курс/pythonProject/countries.csv')
# import_age_limits(connection, 'C:/Users/Даша/Desktop/Учеба/2 курс/pythonProject/age_limits.csv')
# import_genres(connection, 'C:/Users/Даша/Desktop/Учеба/2 курс/pythonProject/genres.csv')
# import_directors(connection, 'C:/Users/Даша/Desktop/Учеба/2 курс/pythonProject/directors.csv')
# import_actors(connection, 'C:/Users/Даша/Desktop/Учеба/2 курс/pythonProject/actors.csv')
# import_films(connection, 'C:/Users/Даша/Desktop/Учеба/2 курс/pythonProject/films.csv')
# import_genre_films(connection, 'C:/Users/Даша/Desktop/Учеба/2 курс/pythonProject/genre_films.csv')
# import_cast_films(connection, 'C:/Users/Даша/Desktop/Учеба/2 курс/pythonProject/cast_films.csv')


connection.close()
print("Импорт завершён.")