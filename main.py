import telebot
from telebot import types
import os
import pandas as pd
from rapidfuzz import process
from dotenv import load_dotenv
import os
import pymysql
from datetime import datetime
import time


load_dotenv()

bot = telebot.TeleBot(os.getenv('BOT_KEY'))
db_password = os.getenv('DB_PASSWORD')


FILTER_TTL_SECONDS = 300 

def clean_old_filters():
    now = time.time()
    to_delete = [uid for uid, data in user_selected_filters.items() if now - data['timestamp'] > FILTER_TTL_SECONDS]
    for uid in to_delete:
        del user_selected_filters[uid]
        log_error(f"Удалён просроченный фильтр пользователя {uid}", level='INFO')


def update_filter_timestamp(user_id):
    if user_id in user_selected_filters:
        user_selected_filters[user_id]['timestamp'] = time.time()


def is_filter_expired(user_id):
    data = user_selected_filters.get(user_id)
    if not data:
        return False
    return time.time() - data.get('timestamp', 0) > FILTER_TTL_SECONDS


def check_expired_and_reset(user_id, chat_id, message_obj):
    if is_filter_expired(user_id):
        user_selected_filters.pop(user_id, None)
        bot.send_message(chat_id, 'Кажется, вы немного задержались с выбором. Чтобы всё сработало корректно, начнём подбор фильмов заново 😊')
        start(message_obj)
        return True
    return False


def log_error(message, level='ERROR'):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open('errors.log', 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] [{level}] {message}\n")


def connect_db():
    try:
        return pymysql.connect(
            host='localhost',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='cinema_bot',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.MySQLError as e:
        log_error(f"Ошибка подключения к базе данных: {str(e)}")
        return None


def rand_film_name():
    conn = connect_db()
    if not conn:
        return None
    with conn.cursor() as cursor:
        cursor.execute("SELECT name FROM films ORDER BY RAND() LIMIT 1")
        result = cursor.fetchone()
        return result['name'] if result else None


def correct_spelling(name, choices):
    # Нормализуем: нижний регистр и обрезаем пробелы
    name = name.strip().lower()
    choices_lower = [c.strip().lower() for c in choices]

    # Получаем индекс лучшего совпадения
    match = process.extractOne(name, choices_lower)

    if match:
        best_match_lower = match[0]
        score = match[1] if isinstance(match, tuple) else getattr(match, "score", 0)
        if score > 70:
            # Возвращаем оригинальное имя из списка (в оригинальной регистровке)
            for original in choices:
                if original.lower() == best_match_lower:
                    return original
    return None


user_selected_filters = {}


def on_click_show_films(message):
    clean_old_filters() 
    user_id = message.from_user.id
    if check_expired_and_reset(user_id, message.chat.id, message):
        return
    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)
    
    films = get_filtered_films(user_filters)

    if films:
        bot.send_message(message.chat.id, "Вот фильмы по выбранным критериям:")
        show_next_films(message, films, 0)
        log_error(f"Пользователь {message.from_user.id} получил подборку фильмов по фильтрам: {user_filters}", level='INFO')
    else:
        bot.send_message(message.chat.id, "Фильмов по выбранным критериям не найдено.")
        show_main_menu(message)
        log_error(f"Пользователь {message.from_user.id} не получил ни одного фильма по фильтрам: {user_filters}", level='INFO')
    user_selected_filters.pop(user_id, None)


def show_next_films(message, films, start_index):
    end_index = start_index + 5
    films_to_show = films[start_index:end_index]
    numbered_films = [f"{i + 1}. {film}" for i, film in enumerate(films_to_show, start=start_index)]
    bot.send_message(message.chat.id, "\n".join(numbered_films))
    if end_index < len(films):
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn_more = types.KeyboardButton('Показать еще')
        btn_done = types.KeyboardButton('Завершить')
        markup.row(btn_more, btn_done)
        bot.send_message(message.chat.id, "Показать еще фильмы?", reply_markup=markup)
        bot.register_next_step_handler(message, lambda msg: on_more_films(msg, films, end_index))
    else:
        ask_to_rate_selection(message, films)


def on_more_films(message, films, current_index):
    if message.text == 'Показать еще':
        show_next_films(message, films, current_index)
    else:
        ask_to_rate_selection(message, films)


def ask_to_rate_selection(message, films):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton('Да'), types.KeyboardButton('Нет'))
    bot.send_message(message.chat.id, 'Хотите оценить эту подборку фильмов?', reply_markup=markup)
    bot.register_next_step_handler(message, lambda msg: handle_selection_rating_response(msg, films))


def handle_selection_rating_response(message, films):
    if message.text.lower() == 'да':
        bot.send_message(message.chat.id, 'Отлично! Давайте оценим каждый фильм.')
        rate_next_film(message, films, 0)
    else:
        bot.send_message(message.chat.id, 'Хорошо, может быть в следующий раз.')
        show_main_menu(message)


def rate_next_film(message, films, index):
    if index < len(films) and index <= 4:
        rate_film(message, films[index])
        bot.register_next_step_handler(message, lambda msg: rate_next_film(msg, films, index + 1))
    else:
        bot.send_message(message.chat.id, 'Спасибо за ваши оценки!')
        show_main_menu(message)


def filter_films_with_all_genres(genre_names):
    if not genre_names:
        return []

    conn = connect_db()
    if not conn:
        return []

    with conn:
        with conn.cursor() as cursor:
            format_strings = ','.join(['%s'] * len(genre_names))
            cursor.execute(f"SELECT id FROM genres WHERE name IN ({format_strings})", genre_names)
            genre_ids = [row['id'] for row in cursor.fetchall()]

            if not genre_ids:
                return []

            cursor.execute(f"""
                SELECT id_film, COUNT(DISTINCT id_genre) as genre_count
                FROM genre_films
                WHERE id_genre IN ({','.join(['%s'] * len(genre_ids))})
                GROUP BY id_film
                HAVING genre_count = %s
            """, genre_ids + [len(genre_ids)])

            result = cursor.fetchall()
            return [row['id_film'] for row in result]


def get_filtered_films(filters):
    query = "SELECT * FROM films"
    conditions = []
    params = []

    if 'Год' in filters:
        conditions.append("year BETWEEN %s AND %s")
        params.extend(filters['Год'])

    if 'Длительность' in filters:
        conditions.append("duration BETWEEN %s AND %s")
        params.extend(filters['Длительность'])

    if 'Рейтинг' in filters:
        conditions.append("rating BETWEEN %s AND %s")
        params.extend(filters['Рейтинг'])

    if 'Страна' in filters:
        country_ids = get_country_ids(filters['Страна'])
        if country_ids:
            placeholders = ', '.join(['%s'] * len(country_ids))
            conditions.append(f"id_country IN ({placeholders})")
            params.extend(country_ids)

    if 'Возрастное ограничение' in filters:
        age_id = get_age_limit_id(filters['Возрастное ограничение'])
        if age_id:
            conditions.append("id_age_limit = %s")
            params.append(age_id)

    if 'Режиссер' in filters:
        director_id = get_director_id(filters['Режиссер'])
        if director_id:
            conditions.append("id_director = %s")
            params.append(director_id)

    film_ids = None

    if 'Актеры' in filters:
        actor_filter = filters['Актеры']
        actor_names = actor_filter.get('names', [])
        match_all = actor_filter.get('match_all', False)

        actor_film_ids = get_actor_film_ids(actor_names, match_all=match_all)

        film_ids = set(actor_film_ids) if film_ids is None else film_ids & set(actor_film_ids)


    if 'Жанр' in filters:
        genre_names = filters['Жанр']
        match_all = filters.get('Жанр_тип') == 'AND'

        if match_all:
            genre_film_ids = filter_films_with_all_genres(genre_names)
        else:
            genre_film_ids = get_genre_film_ids(genre_names)

        film_ids = set(genre_film_ids) if film_ids is None else film_ids & set(genre_film_ids)


    if film_ids is not None:
        if not film_ids:
            return []
        placeholders = ', '.join(['%s'] * len(film_ids))
        conditions.append(f"id IN ({placeholders})")
        params.extend(film_ids)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    conn = connect_db()
    if not conn:
        return None
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        result = cursor.fetchall()
        films = [row['name'] for row in result]
        if film_ids is not None:
            with_ids = get_film_ids_by_names(films, conn)
            films = [name for name, fid in with_ids if fid in film_ids]
        return films


def get_country_ids(names):
    if isinstance(names, str):
        names = [names]
    conn = connect_db()
    if not conn:
        return []
    with conn:
        with conn.cursor() as cursor:
            format_strings = ','.join(['%s'] * len(names))
            cursor.execute(f"SELECT id FROM countries WHERE name IN ({format_strings})", names)
            rows = cursor.fetchall()
            return [row['id'] for row in rows]


def get_age_limit_id(label):
    conn = connect_db()
    if not conn:
        return None
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM age_limits WHERE label = %s", (label,))
            row = cursor.fetchone()
            return row['id'] if row else None


def get_director_id(surname):
    surname = surname.strip().lower()
    conn = connect_db()
    if not conn:
        return None
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM directors WHERE LOWER(surname) = %s", (surname,))
            row = cursor.fetchone()
            return row['id'] if row else None


def get_actor_film_ids(actor_names, match_all=False):
    if isinstance(actor_names, str):
        actor_names = [actor_names.strip().lower()]
    else:
        actor_names = [name.strip().lower() for name in actor_names]

    conn = connect_db()
    if not conn:
        return []

    with conn:
        with conn.cursor() as cursor:
            format_strings = ','.join(['%s'] * len(actor_names))
            cursor.execute(f"SELECT id, surname FROM actors WHERE LOWER(surname) IN ({format_strings})", actor_names)
            actor_rows = cursor.fetchall()

            if not actor_rows:
                return []

            actor_ids = [row['id'] for row in actor_rows]

            if not actor_ids:
                return []

            cursor.execute(f"""
                SELECT id_film, id_actor FROM cast_films
                WHERE id_actor IN ({','.join(['%s'] * len(actor_ids))})
            """, actor_ids)

            results = cursor.fetchall()
            if not results:
                return []

            from collections import defaultdict
            film_to_actors = defaultdict(set)
            for row in results:
                film_to_actors[row['id_film']].add(row['id_actor'])

            if match_all:
                return [film_id for film_id, actor_set in film_to_actors.items() if set(actor_ids).issubset(actor_set)]
            else:
                return list(film_to_actors.keys())


def get_genre_film_ids(genres):
    if isinstance(genres, str):
        genres = [genres]

    conn = connect_db()
    if not conn:
        return []

    with conn:
        with conn.cursor() as cursor:
            format_strings = ','.join(['%s'] * len(genres))
            cursor.execute(f"SELECT id FROM genres WHERE name IN ({format_strings})", genres)
            genre_rows = cursor.fetchall()
            if not genre_rows:
                return []

            genre_ids = [row['id'] for row in genre_rows]

            cursor.execute(f"""
                SELECT id_film FROM genre_films 
                WHERE id_genre IN ({','.join(['%s'] * len(genre_ids))})
            """, genre_ids)
            result = cursor.fetchall()
            return [row['id_film'] for row in result]


def get_film_id_by_name(connection, film_name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM films WHERE name = %s", (film_name,))
        result = cursor.fetchone()
        return result['id'] if result else None


def get_film_ids_by_names(names, connection):
    if not names:
        return []
    with connection.cursor() as cursor:
        format_strings = ','.join(['%s'] * len(names))
        cursor.execute(f"SELECT name, id FROM films WHERE name IN ({format_strings})", names)
        return [(row['name'], row['id']) for row in cursor.fetchall()]


def save_user_rating(connection, user_id, film_id, rating):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO ratings (user_id, film_id, rating)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE rating = VALUES(rating)
            """, (user_id, film_id, rating))
        connection.commit()
        log_error(f"Оценка сохранена: user_id={user_id}, film_id={film_id}, rating={rating}", level='INFO')
    except Exception as e:
        log_error(f"Ошибка при сохранении оценки: user_id={user_id}, film_id={film_id}, rating={rating}, ошибка: {str(e)}")


def get_rating_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row(*(types.KeyboardButton(str(i)) for i in range(1, 4)))
    markup.row(*(types.KeyboardButton(str(i)) for i in range(4, 6)))
    markup.row(
        types.KeyboardButton('Не хочу оценивать'),
        types.KeyboardButton('Не смотрел(-а)')
    )
    return markup


def mark_film_as_watched(connection, user_id, film_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT IGNORE INTO watched (user_id, id_film)
                VALUES (%s, %s)
            """, (user_id, film_id))
        connection.commit()
        log_error(f"Фильм отмечен как просмотренный: user_id={user_id}, film_id={film_id}", level='INFO')
    except Exception as e:
        log_error(f"Ошибка при записи просмотра: user_id={user_id}, film_id={film_id}, ошибка: {str(e)}")


def rate_film(message, film_name):
    if film_name is None:
        bot.send_message(message.chat.id, 'Фильм не найден, повторите попытку позже.')
        log_error("Передан None в rate_film()")
        show_main_menu(message)
        return

    markup = get_rating_markup()
    bot.send_message(message.chat.id, f'Оцените фильм "{film_name}" от 1 до 5:', reply_markup=markup)
    bot.register_next_step_handler(message, lambda msg: get_rating(msg, film_name))


def rate_random_film(message, film_name):
    if film_name is None:
        bot.send_message(message.chat.id, 'Фильм не найден, повторите попытку позже.')
        log_error("Передан None в rate_random_film()")
        show_main_menu(message)
        return

    markup = get_rating_markup()
    bot.send_message(message.chat.id, 'Оцените фильм от 1 до 5:', reply_markup=markup)
    bot.register_next_step_handler(message, lambda msg: get_rating_random(msg, film_name))


def get_rating(message, film_name):
    if message.text == 'Не хочу оценивать':
        return
    if message.text == 'Не смотрел(-а)':
        # bot.send_message(message.chat.id, 'Хорошо! Мы не будем сохранять информацию об этом фильме.')
        # show_main_menu(message)
        return
    try:
        rating = int(message.text)
        if 1 <= rating <= 5:
            conn = connect_db()
            if not conn:
                bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
                return
            with conn:
                film_id = get_film_id_by_name(conn, film_name)
                if film_id:
                    save_user_rating(conn, message.from_user.id, film_id, rating)
                    mark_film_as_watched(conn, message.from_user.id, film_id)
                else:
                    bot.send_message(message.chat.id, 'Фильм не найден в базе данных.')
                    log_error(f"Фильм не найден в базе данных: '{film_name}'")
        else:
            bot.send_message(message.chat.id, 'Пожалуйста, введите число от 1 до 5.')
            rate_film(message, film_name)
    except ValueError:
        log_error(f"Неверный ввод от пользователя {message.from_user.id}: {message.text}", level='WARNING')
        bot.send_message(message.chat.id, 'Пожалуйста, введите число от 1 до 5.')
        bot.register_next_step_handler(message, lambda msg: get_rating(msg, film_name))


def get_rating_random(message, film_name):
    if message.text == 'Не хочу оценивать':
        bot.send_message(message.chat.id, 'Спасибо! (Хоть вы и не оценили фильм.)')
        show_main_menu(message)
        return
    if message.text == 'Не смотрел(-а)':
        bot.send_message(message.chat.id, 'Хорошо! Мы не будем сохранять информацию об этом фильме.')
        show_main_menu(message)
        return
    try:
        rating = int(message.text)
        if 1 <= rating <= 5:
            conn = connect_db()
            if not conn:
                bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
                return
            with conn:
                film_id = get_film_id_by_name(conn, film_name)
                if film_id:
                    save_user_rating(conn, message.from_user.id, film_id, rating)
                    mark_film_as_watched(conn, message.from_user.id, film_id)
                    bot.send_message(message.chat.id, 'Спасибо за вашу оценку!')
                else:
                    bot.send_message(message.chat.id, 'Фильм не найден в базе данных.')
                    log_error(f"Фильм не найден в базе данных: '{film_name}'")
        else:
            bot.send_message(message.chat.id, 'Пожалуйста, введите число от 1 до 5.')
            rate_random_film(message, film_name)
    except ValueError:
        bot.send_message(message.chat.id, 'Пожалуйста, введите число от 1 до 5.')
        bot.register_next_step_handler(message, lambda msg: get_rating_random(msg, film_name))
    finally:
        show_main_menu(message)


def recommend_films(user_id):
    try:
        conn = connect_db()
        if not conn:
            return None
        with conn:
            df = pd.read_sql("SELECT user_id, film_id, rating FROM ratings", conn)

            if df.empty:
                return []

            user_film_matrix = df.pivot_table(index='user_id', columns='film_id', values='rating').fillna(0)

            try:
                user_ratings = user_film_matrix.loc[user_id]
                films_not_watched = user_ratings[user_ratings == 0].index.tolist()
            except KeyError:
                films_not_watched = user_film_matrix.columns.tolist()

            user_stddev = user_film_matrix.std(axis=1)
            user_film_matrix = user_film_matrix[user_stddev != 0]

            if user_id not in user_film_matrix.index:
                return []

            similar_users = user_film_matrix.corrwith(user_film_matrix.loc[user_id], axis=1).dropna()
            similar_users = similar_users[similar_users > 0].sort_values(ascending=False)

            film_recommendations = {}
            for user, similarity in similar_users.items():
                ratings = user_film_matrix.loc[user]
                for film_id, rating in ratings.items():
                    if user_film_matrix.at[user_id, film_id] == 0 and film_id in films_not_watched:
                        film_recommendations[film_id] = film_recommendations.get(film_id, 0) + similarity * rating

            if not film_recommendations:
                return []

            recommended_ids = sorted(film_recommendations.items(), key=lambda x: x[1], reverse=True)
            top_ids = [film_id for film_id, _ in recommended_ids[:5]]

            if not top_ids:
                return []

            with conn.cursor() as cursor:
                format_strings = ','.join(['%s'] * len(top_ids))
                cursor.execute(f"SELECT name FROM films WHERE id IN ({format_strings})", top_ids)
                rows = cursor.fetchall()

                if not rows:
                    log_error(f"Рекомендованные фильмы не найдены в таблице films: {top_ids}")
                    return []
            
                log_error(f"Пользователю {user_id} выданы рекомендации: {top_ids}", level='INFO')
                return [row['name'] for row in rows]
    except Exception as e:
        log_error(f"Ошибка при формировании рекомендаций: {str(e)}")
        return []


@bot.message_handler(commands=['start'])
def start(message):
    clean_old_filters()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton('Подборка фильмов')
    btn2 = types.KeyboardButton('Случайный фильм')
    btn3 = types.KeyboardButton('Рекомендации')
    btn4 = types.KeyboardButton('Завершить работу')
    markup.row(btn1, btn2)
    markup.row(btn3, btn4)
    bot.send_message(message.chat.id, f'Привет, {message.from_user.username}! Выбери, что ты хочешь сделать 👇🏻', reply_markup=markup)
    bot.register_next_step_handler(message, on_click)
    log_error(f"Пользователь {message.from_user.id} начал сессию", level='INFO')


@bot.message_handler(commands=['feedback'])
def feedback_command(message):
    bot.send_message(message.chat.id, 'Напишите ваш отзыв и отправьте его нам.')
    bot.register_next_step_handler(message, save_feedback)


def on_click(message):
    clean_old_filters() 
    if message.text == 'Подборка фильмов':
        filter_choice(message)
    elif message.text == 'Случайный фильм':
        random_film = rand_film_name()
        if random_film:
            bot.send_message(message.chat.id, f"Вот ваш случайный фильм: {random_film}")
            rate_random_film(message, random_film)
        else:
            bot.send_message(message.chat.id, "Не удалось выбрать случайный фильм. Попробуйте позже.")
            log_error("Не удалось выбрать случайный фильм: rand_film_name() вернул None")
    elif message.text == 'Рекомендации':
        user_id = message.from_user.id
        recommended_films = recommend_films(user_id)
        if not recommended_films:
            bot.send_message(message.chat.id, 'Нет новых рекомендаций на данный момент.')
        else:
            recommendations_str = '\n'.join([f"{i + 1}. {film_id}" for i, film_id in enumerate(recommended_films)])
            bot.send_message(message.chat.id, f"Вот ваши рекомендации:\n{recommendations_str}")
        show_main_menu(message)
    elif message.text == 'Оставить отзыв на работу бота':
        bot.send_message(message.chat.id, 'Напишите ваш отзыв и отправьте его нам.')
        bot.register_next_step_handler(message, save_feedback)
    elif message.text == 'Завершить работу':
        user_selected_filters.pop(message.from_user.id, None)
        hide_keyboard = types.ReplyKeyboardRemove()
        bot.send_message(message.chat.id, "До скорых встреч!", reply_markup=hide_keyboard)
    else:
        bot.send_message(message.chat.id, 'Пожалуйста, выберите одно из предложенных действий.')
        start(message)


def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton('Подборка фильмов')
    btn2 = types.KeyboardButton('Случайный фильм')
    btn3 = types.KeyboardButton('Рекомендации')
    btn4 = types.KeyboardButton('Завершить работу')
    markup.row(btn1, btn2)
    markup.row(btn3, btn4)
    bot.send_message(message.chat.id, 'Что бы вы хотели сделать дальше?', reply_markup=markup)
    bot.register_next_step_handler(message, on_click)


def save_feedback(message):
    feedback = message.text
    with open('feedback.txt', 'a', encoding='utf-8') as f:
        f.write(f"{message.from_user.username}: {feedback}\n")
    log_error(f"Получен отзыв от {message.from_user.username}: {feedback}", level='INFO')
    bot.send_message(message.chat.id, 'Спасибо за ваш отзыв!')
    show_main_menu(message)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    clean_old_filters() 
    log_error(f"Пользователь {message.from_user.id} ввёл неизвестную команду: {message.text}", level='INFO')
    bot.send_message(message.chat.id, 'Неизвестная команда. Пожалуйста, выберите одну из предложенных опций.')
    show_main_menu(message)


def filter_choice(message):
    user_id = message.from_user.id
    if check_expired_and_reset(user_id, message.chat.id, message):
        return
    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton('Год')
    btn7 = types.KeyboardButton('Возрастное ограничение')
    btn2 = types.KeyboardButton('Жанр')
    btn4 = types.KeyboardButton('Режиссер')
    btn5 = types.KeyboardButton('Страна')
    btn8 = types.KeyboardButton('Длительность')
    btn6 = types.KeyboardButton('Рейтинг')
    btn3 = types.KeyboardButton('Актеры')
    btn_done = types.KeyboardButton('Показать фильмы')
    btn_back = types.KeyboardButton('Отменить последний выбор')
    markup.row(btn1, btn2, btn3)
    markup.row(btn4, btn5, btn6)
    markup.row(btn7, btn8, btn_back)
    markup.row(btn_done)
    
    bot.send_message(message.chat.id, 'Выберите критерий, который важен вам при выборе фильма 👇🏻', reply_markup=markup)

    user_selected_filters[user_id] = user_filters
    bot.register_next_step_handler(message, on_click_filter)


def on_click_filter(message):
    clean_old_filters() 
    user_id = message.from_user.id
    if check_expired_and_reset(user_id, message.chat.id, message):
        return
    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)

    if message.text == 'Отменить последний выбор':
        filters_only = {k: v for k, v in user_filters.items() if k != 'timestamp'}
        if filters_only:
            user_filters.popitem()
            bot.send_message(message.chat.id, 'Последний выбранный фильтр удалён.')
        else:
            bot.send_message(
                message.chat.id,
                'Вы ещё не выбрали ни одного критерия.'
            )
        filter_choice(message)
        return
    filter_type = message.text
    if message.text not in user_filters:
        user_filters[message.text] = None
    if message.text == 'Показать фильмы':
        user_id = message.from_user.id
        user_filters = user_selected_filters.setdefault(user_id, {})
        filters_text = get_filters_summary(user_filters)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Показать подборку", callback_data="show_films_confirmed"))
        markup.add(types.InlineKeyboardButton("Изменить фильтры", callback_data="change_filters"))
        bot.send_message(message.chat.id, f"Вы выбрали:\n\n{filters_text}\n\nПоказать подборку с этими фильтрами или изменить фильтры?", reply_markup=markup)
        return
    if message.text == 'Год':
        markup_inline = types.InlineKeyboardMarkup()
        btn1 = types.InlineKeyboardButton('до 1950', callback_data='year_1')
        btn2 = types.InlineKeyboardButton('1950 - 1969', callback_data='year_2')
        btn3 = types.InlineKeyboardButton('1970 - 1979', callback_data='year_3')
        btn4 = types.InlineKeyboardButton('1980 - 1989', callback_data='year_4')
        btn5 = types.InlineKeyboardButton('1990 - 1999', callback_data='year_5')
        btn6 = types.InlineKeyboardButton('2000 - 2004', callback_data='year_6')
        btn7 = types.InlineKeyboardButton('2005 - 2009', callback_data='year_7')
        btn8 = types.InlineKeyboardButton('2010 - 2014', callback_data='year_8')
        btn9 = types.InlineKeyboardButton('2015 - 2019', callback_data='year_9')
        btn10 = types.InlineKeyboardButton('2020 - 2024', callback_data='year_10')
        markup_inline.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8, btn9, btn10)
        bot.send_message(message.chat.id, 'Какого года фильм ты хочешь посмотреть?', reply_markup=markup_inline)
    elif message.text == 'Длительность':
        markup_inline = types.InlineKeyboardMarkup()
        btn1 = types.InlineKeyboardButton('меньше 1ч', callback_data='duration_1')
        btn2 = types.InlineKeyboardButton('от 1ч до 1.5ч', callback_data='duration_2')
        btn3 = types.InlineKeyboardButton('от 1.5ч до 2ч', callback_data='duration_3')
        btn4 = types.InlineKeyboardButton('больше 2ч', callback_data='duration_4')
        markup_inline.add(btn1, btn2, btn3, btn4)
        bot.send_message(message.chat.id, 'Какой длительности фильм ты хочешь посмотреть?', reply_markup=markup_inline)
    elif message.text == 'Страна':
        markup_inline = types.InlineKeyboardMarkup()
        btn1 = types.InlineKeyboardButton('Россия', callback_data='country_Россия')
        btn2 = types.InlineKeyboardButton('США', callback_data='country_США')
        btn3 = types.InlineKeyboardButton('Великобритания', callback_data='country_Великобритания')
        btn4 = types.InlineKeyboardButton('СССР', callback_data='country_СССР')
        btn5 = types.InlineKeyboardButton('Франция', callback_data='country_Франция')
        btn6 = types.InlineKeyboardButton('Германия', callback_data='country_Германия')
        btn7 = types.InlineKeyboardButton('Южная Корея', callback_data='country_Южная Корея')
        btn8 = types.InlineKeyboardButton('Дания', callback_data='country_Дания')
        btn9 = types.InlineKeyboardButton('Испания', callback_data='country_Испания')
        markup_inline.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8, btn9)
        bot.send_message(message.chat.id, 'Какой страны фильм ты хочешь посмотреть?', reply_markup=markup_inline)
    elif message.text == 'Режиссер':
        bot.send_message(message.chat.id, 'Введи фамилию режиссера, фильм которого хотел(-а) бы посмотреть')
        bot.register_next_step_handler(message, on_click_director)
    elif message.text == 'Возрастное ограничение':
        markup_inline = types.InlineKeyboardMarkup()
        btn1 = types.InlineKeyboardButton('0+', callback_data='limit_0+')
        btn2 = types.InlineKeyboardButton('6+', callback_data='limit_6+')
        btn3 = types.InlineKeyboardButton('12+', callback_data='limit_12+')
        btn4 = types.InlineKeyboardButton('16+', callback_data='limit_16+')
        btn5 = types.InlineKeyboardButton('18+', callback_data='limit_18+')
        markup_inline.add(btn1, btn2, btn3, btn4, btn5)
        bot.send_message(message.chat.id, 'Фильм с каким возрастным ограничением ты хочешь посмотреть?', reply_markup=markup_inline)
    elif message.text == 'Рейтинг':
        markup_inline = types.InlineKeyboardMarkup()
        btn1 = types.InlineKeyboardButton('до 6.0', callback_data='rating_low')
        btn2 = types.InlineKeyboardButton('6.0+', callback_data='rating_6+')
        btn3 = types.InlineKeyboardButton('7.0+', callback_data='rating_7+')
        btn4 = types.InlineKeyboardButton('8.0+', callback_data='rating_8+')
        btn5 = types.InlineKeyboardButton('9.0+', callback_data='rating_9+')
        markup_inline.add(btn1, btn2, btn3, btn4, btn5)
        bot.reply_to(message, 'Какой рейтинг должен быть у фильма?', reply_markup=markup_inline)
    elif message.text == 'Актеры':
        bot.send_message(message.chat.id, 'Введи фамилии актёров через запятую')
        bot.register_next_step_handler(message, on_actor_input)
    elif message.text == 'Жанр':
        markup_inline = types.InlineKeyboardMarkup()
        btn1 = types.InlineKeyboardButton('Аниме', callback_data='genre_Аниме')
        btn2 = types.InlineKeyboardButton('Биография', callback_data='genre_Биография')
        btn3 = types.InlineKeyboardButton('Боевик', callback_data='genre_Боевик')
        btn4 = types.InlineKeyboardButton('Вестерн', callback_data='genre_Вестерн')
        btn5 = types.InlineKeyboardButton('Военный', callback_data='genre_Военный')
        btn6 = types.InlineKeyboardButton('Детектив', callback_data='genre_Детектив')
        btn7 = types.InlineKeyboardButton('Документальный', callback_data='genre_Документальный')
        btn8 = types.InlineKeyboardButton('Драма', callback_data='genre_Драма')
        btn9 = types.InlineKeyboardButton('Исторический', callback_data='genre_Исторический')
        btn10 = types.InlineKeyboardButton('Комедия', callback_data='genre_Комедия')
        btn11 = types.InlineKeyboardButton('Короткометражка', callback_data='genre_Короткометражка')
        btn12 = types.InlineKeyboardButton('Криминал', callback_data='genre_Криминал')
        btn13 = types.InlineKeyboardButton('Мелодрама', callback_data='genre_Мелодрама')
        btn14 = types.InlineKeyboardButton('Музыка', callback_data='genre_Музыка')
        btn15 = types.InlineKeyboardButton('Мультфильм', callback_data='genre_Мультфильм')
        btn16 = types.InlineKeyboardButton('Мюзикл', callback_data='genre_Мюзикл')
        btn17 = types.InlineKeyboardButton('Приключения', callback_data='genre_Приключения')
        btn18 = types.InlineKeyboardButton('Семейный', callback_data='genre_Семейный')
        btn19 = types.InlineKeyboardButton('Спорт', callback_data='genre_Спорт')
        btn20 = types.InlineKeyboardButton('Триллер', callback_data='genre_Триллер')
        btn21 = types.InlineKeyboardButton('Ужасы', callback_data='genre_Ужасы')
        btn22 = types.InlineKeyboardButton('Фантастика', callback_data='genre_Фантастика')
        btn23 = types.InlineKeyboardButton('Нуар', callback_data='genre_Нуар')
        btn24 = types.InlineKeyboardButton('Фэнтези', callback_data='genre_Фэнтези')
        btn25 = types.InlineKeyboardButton('Мистика', callback_data='genre_Мистика')
        markup_inline.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8, btn9, btn10, btn11, btn12, btn13, btn14,
                          btn15, btn16, btn17, btn18, btn19, btn20, btn21, btn22, btn23, btn24, btn25)
        bot.reply_to(message, 'Фильм какого жанра ты хочешь посмотреть?', reply_markup=markup_inline)
    else:
        bot.send_message(message.chat.id, 'Пожалуйста, выберите один из предложенных критериев.')
        filter_choice(message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('year_'))
def on_click_year(call):
    clean_old_filters() 
    user_id = call.from_user.id
    if check_expired_and_reset(user_id, call.message.chat.id, call.message):
        return
    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)

    year_ranges = {
        'year_1': (0, 1949),
        'year_2': (1950, 1969),
        'year_3': (1970, 1979),
        'year_4': (1980, 1989),
        'year_5': (1990, 1999),
        'year_6': (2000, 2004),
        'year_7': (2005, 2009),
        'year_8': (2010, 2014),
        'year_9': (2015, 2019),
        'year_10': (2020, 2024),
    }
    year1, year2 = year_ranges[call.data]
    user_filters['Год'] = (year1, year2)
    filter_choice(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('duration_'))
def on_click_duration(call):
    clean_old_filters() 
    user_id = call.from_user.id
    if check_expired_and_reset(user_id, call.message.chat.id, call.message):
        return
    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)

    duration_ranges = {
        'duration_1': (0, 59),
        'duration_2': (60, 89),
        'duration_3': (90, 119),
        'duration_4': (120, 500),
    }
    dur1, dur2 = duration_ranges[call.data]
    user_filters['Длительность'] = (dur1, dur2)
    filter_choice(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('rating_'))
def on_click_rating(call):
    clean_old_filters() 
    user_id = call.from_user.id
    if check_expired_and_reset(user_id, call.message.chat.id, call.message):
        return
    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)

    rating_ranges = {
        'rating_low': (0, 5.9),
        'rating_6+': (6.0, 10.0),
        'rating_7+': (7.0, 10.0),
        'rating_8+': (8.0, 10.0),
        'rating_9+': (9.0, 10.0),
    }

    rating1, rating2 = rating_ranges[call.data]
    user_filters['Рейтинг'] = (rating1, rating2)
    filter_choice(call.message)


@bot.callback_query_handler(func=lambda call: call.data == 'country_done')
def on_done_country(call):

    clean_old_filters()
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    log_error(f"country_done нажата пользователем {user_id}", level='INFO')

    if check_expired_and_reset(user_id, chat_id, call.message):
        return

    selected = user_selected_filters.get(user_id, {}).get('Страна', [])

    if not selected:
        bot.send_message(chat_id, "Вы не выбрали ни одной страны.")
    else:
        bot.send_message(chat_id, f"Вы выбрали: {', '.join(selected)}")

    filter_choice(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('country_'))
def on_click_country(call):
    clean_old_filters()
    if call.data == 'country_done':
        return
    
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    if check_expired_and_reset(user_id, chat_id, call.message):
        return

    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)

    if 'Страна' not in user_filters or not isinstance(user_filters['Страна'], list):
        user_filters['Страна'] = []

    # Инициализируем список, если его нет
    selected_countries = user_filters.setdefault('Страна', [])

    country = call.data.split('_', 1)[1]

    if country in selected_countries:
        selected_countries.remove(country)
    else:
        selected_countries.append(country)

    all_countries = [
        'Россия', 'США', 'Великобритания', 'СССР', 'Франция',
        'Германия', 'Южная Корея', 'Дания', 'Испания'
    ]

    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    for c in all_countries:
        is_selected = "✅ " if c in selected_countries else ""
        buttons.append(types.InlineKeyboardButton(f"{is_selected}{c}", callback_data=f'country_{c}'))

    # Добавим кнопки по 3 в ряд
    for i in range(0, len(buttons), 3):
        markup.row(*buttons[i:i+3])

    # Добавляем кнопку "Готово"
    markup.add(types.InlineKeyboardButton("Готово", callback_data="country_done"))

    try:
        # Удаляем предыдущее сообщение
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        log_error(f"Ошибка при удалении сообщения: {str(e)}", level="WARNING")

    # Отправляем новое с обновлённой разметкой
    bot.send_message(chat_id, "Выберите страну или нажмите 'Готово':", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('limit_'))
def on_click_age_limit(call):
    clean_old_filters() 
    user_id = call.from_user.id
    if check_expired_and_reset(user_id, call.message.chat.id, call.message):
        return
    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)
    
    age_limit = call.data.split('_')[1]
    user_filters['Возрастное ограничение'] = age_limit
    filter_choice(call.message)


def on_click_director(message):
    clean_old_filters() 
    user_id = message.from_user.id
    if check_expired_and_reset(user_id, message.chat.id, message):
        return
    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)
    
    user_input = message.text.strip()
    conn = connect_db()
    if not conn:
        bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
        return
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT surname FROM directors")
            director_surnames = [row['surname'] for row in cursor.fetchall()]
    corrected = correct_spelling(user_input, director_surnames)
    if corrected:
        user_filters['Режиссер'] = corrected
        filter_choice(message)
    else:
        bot.send_message(message.chat.id, "Режиссёр не найден. Попробуйте ещё раз.")
        bot.register_next_step_handler(message, on_click_director)


def on_click_actor(message):
    clean_old_filters()
    user_id = message.from_user.id
    if check_expired_and_reset(user_id, message.chat.id, message):
        return

    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)

    # Получаем список актёров
    input_text = message.text.strip()
    actor_names = [name.strip() for name in input_text.split(',') if name.strip()]

    if not actor_names:
        bot.send_message(message.chat.id, "Пожалуйста, введите хотя бы одного актёра через запятую.")
        bot.register_next_step_handler(message, on_click_actor)
        return

    user_filters['Актеры'] = {
        'names': actor_names,
        'match_all': False  # по умолчанию
    }

    # Предлагаем выбрать режим
    markup = types.InlineKeyboardMarkup()
    btn_all = types.InlineKeyboardButton('Все актёры', callback_data='actors_mode_AND')
    btn_any = types.InlineKeyboardButton('Любой актёр', callback_data='actors_mode_OR')
    markup.add(btn_all, btn_any)

    bot.send_message(message.chat.id, "Искать фильмы, у которых есть все выбранные актеры, или достаточно любого из них?", reply_markup=markup)


def on_actor_input(message):
    clean_old_filters()
    user_id = message.from_user.id
    if check_expired_and_reset(user_id, message.chat.id, message):
        return

    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)

    raw_input = message.text.strip()
    actor_names_input = [name.strip() for name in raw_input.split(',') if name.strip()]
    if not actor_names_input:
        bot.send_message(message.chat.id, "Вы не ввели ни одного имени. Попробуйте ещё раз.")
        bot.register_next_step_handler(message, on_actor_input)
        return

    # Загружаем все фамилии из базы
    conn = connect_db()
    if not conn:
        bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
        return

    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT surname FROM actors")
            all_actor_surnames = [row['surname'] for row in cursor.fetchall()]

    # Проверяем каждую введённую фамилию на корректность
    corrected_names = []
    not_found = []
    for name in actor_names_input:
        corrected = correct_spelling(name, all_actor_surnames)
        if corrected:
            corrected_names.append(corrected)
        else:
            not_found.append(name)

    if not corrected_names:
        bot.send_message(message.chat.id, "Ни одного актёра не найдено. Попробуйте ещё раз.")
        bot.register_next_step_handler(message, on_actor_input)
        return

    if not_found:
        bot.send_message(message.chat.id, f"Эти фамилии не распознаны: {', '.join(not_found)}. Будут проигнорированы.")

    # Сохраняем корректные фамилии временно
    user_filters['_actor_temp'] = corrected_names

    markup = types.InlineKeyboardMarkup()
    btn_all = types.InlineKeyboardButton('Все актёры', callback_data='actor_mode_AND')
    btn_any = types.InlineKeyboardButton('Любой из них', callback_data='actor_mode_OR')
    markup.add(btn_all, btn_any)

    bot.send_message(message.chat.id, 'Искать фильмы, у которых есть все выбранные актеры, или достаточно любого из них?', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('actor_mode_'))
def on_actor_mode_selected(call):
    clean_old_filters()
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if check_expired_and_reset(user_id, chat_id, call.message):
        return

    mode = call.data.split('_')[-1]  # AND или OR
    match_all = (mode == 'AND')
    actor_names = user_selected_filters[user_id].pop('_actor_temp', [])

    user_selected_filters[user_id]['Актеры'] = {
        'names': actor_names,
        'match_all': match_all
    }

    bot.send_message(chat_id, f"Принято. Фильмы с {'всеми' if match_all else 'любым из'} указанных актёров.")
    filter_choice(call.message)


@bot.callback_query_handler(func=lambda call: call.data == 'genre_done')
def on_done_genre(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    selected = user_selected_filters.get(user_id, {}).get('Жанр', [])
    if not selected:
        bot.send_message(chat_id, "Вы не выбрали ни одного жанра.")
        return

    # Здесь спрашиваем пользователя — все жанры в одном фильме или любой из них
    markup = types.InlineKeyboardMarkup()
    btn_all = types.InlineKeyboardButton('Все жанры', callback_data='genre_mode_AND')
    btn_any = types.InlineKeyboardButton('Любой жанр', callback_data='genre_mode_OR')
    markup.add(btn_all, btn_any)

    bot.send_message(chat_id, 'Искать фильмы, у которых есть все выбранные жанры, или достаточно любого из них?', reply_markup=markup)

    # сохраняем выбранные жанры временно
    user_selected_filters[user_id]['_genre_temp'] = selected


@bot.callback_query_handler(func=lambda call: call.data.startswith('genre_mode_'))
def on_genre_mode_selected(call):
    clean_old_filters()
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if check_expired_and_reset(user_id, chat_id, call.message):
        return

    mode = call.data.split('_')[-1]  # AND или OR
    user_selected_filters[user_id]['Жанр_тип'] = mode

    # bot.send_message(chat_id, f"Хорошо, будем искать фильмы по принципу: {'все жанры' if mode == 'AND' else 'любой жанр'}.")
    filter_choice(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('genre_'))
def on_click_genre(call):
    clean_old_filters()
    if call.data == 'genre_done':
        return

    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    if check_expired_and_reset(user_id, chat_id, call.message):
        return

    user_filters = user_selected_filters.setdefault(user_id, {})
    update_filter_timestamp(user_id)

    if 'Жанр' not in user_filters or not isinstance(user_filters['Жанр'], list):
        user_filters['Жанр'] = []

    selected_genres = user_filters['Жанр']
    genre = call.data.split('_', 1)[1]

    if genre in selected_genres:
        selected_genres.remove(genre)
    else:
        selected_genres.append(genre)

    all_genres = [
        'Аниме', 'Биография', 'Боевик', 'Вестерн', 'Военный', 'Детектив',
        'Документальный', 'Драма', 'Исторический', 'Комедия', 'Короткометражка',
        'Криминал', 'Мелодрама', 'Музыка', 'Мультфильм', 'Мюзикл',
        'Приключения', 'Семейный', 'Спорт', 'Триллер', 'Ужасы',
        'Фантастика', 'Нуар', 'Фэнтези', 'Мистика'
    ]

    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    for g in all_genres:
        is_selected = "✅ " if g in selected_genres else ""
        buttons.append(types.InlineKeyboardButton(f"{is_selected}{g}", callback_data=f'genre_{g}'))

    for i in range(0, len(buttons), 3):
        markup.row(*buttons[i:i+3])

    markup.add(types.InlineKeyboardButton("Готово", callback_data="genre_done"))

    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        log_error(f"Ошибка при удалении сообщения: {str(e)}", level="WARNING")

    bot.send_message(chat_id, "Выберите жанры или нажмите 'Готово':", reply_markup=markup)


def get_filters_summary(user_filters):
    summary = []
    if 'Год' in user_filters:
        summary.append(f"Год: {user_filters['Год'][0]}–{user_filters['Год'][1]}")
    if 'Длительность' in user_filters:
        summary.append(f"Длительность: {user_filters['Длительность'][0]}–{user_filters['Длительность'][1]} мин")
    if 'Рейтинг' in user_filters:
        summary.append(f"Рейтинг: {user_filters['Рейтинг'][0]}–{user_filters['Рейтинг'][1]}")
    if 'Страна' in user_filters and user_filters['Страна']:
        summary.append(f"Страны: {', '.join(user_filters['Страна'])}")
    if 'Жанр' in user_filters and user_filters['Жанр']:
        genre_type = user_filters.get('Жанр_тип', 'OR')
        type_str = "Все" if genre_type == 'AND' else "Любой из"
        summary.append(f"Жанры ({type_str}): {', '.join(user_filters['Жанр'])}")
    if 'Режиссер' in user_filters:
        summary.append(f"Режиссер: {user_filters['Режиссер']}")
    if 'Актеры' in user_filters and user_filters['Актеры']:
        actor_type = user_filters['Актеры'].get('match_all', False)
        type_str = "Все" if actor_type else "Любой из"
        actors = ', '.join(user_filters['Актеры']['names'])
        summary.append(f"Актеры ({type_str}): {actors}")
    if 'Возрастное ограничение' in user_filters:
        summary.append(f"Возраст: {user_filters['Возрастное ограничение']}")
    return "\n".join(summary) if summary else "Фильтры не выбраны"


@bot.callback_query_handler(func=lambda call: call.data == 'show_films_confirmed')
def show_films_confirmed_handler(call):
    on_click_show_films(call.message)


@bot.callback_query_handler(func=lambda call: call.data == 'change_filters')
def change_filters_handler(call):
    filter_choice(call.message)


bot.polling(none_stop=True)