import telebot
from telebot import types
import csv
import random
import os
import pandas as pd
from rapidfuzz import process
from dotenv import load_dotenv
import os
import pymysql
from datetime import datetime


load_dotenv()

bot = telebot.TeleBot(os.getenv('BOT_KEY'))
db_password = os.getenv('DB_PASSWORD')


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
            database='cinema-bot',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.MySQLError as e:
        log_error(f"Ошибка подключения к базе данных: {str(e)}")
        return None


line_count = sum(1 for line in open(r'C:\Users\Даша\Desktop\2 курс\pythonProject\films бд.csv', encoding='cp1251')) - 1


def rand_film_name():
    rand_num_of_film = random.randint(1, line_count)
    with open(r'C:\Users\Даша\Desktop\2 курс\pythonProject\films бд.csv', newline='', encoding='cp1251') as csvfile:
        reader = csv.reader(csvfile, delimiter=';')
        next(reader)
        for _ in range(rand_num_of_film):
            row = next(reader)
        return row[1]


def correct_spelling(name, choices):
    best_match, score = process.extractOne(name, choices)
    if score > 80:  # Порог схожести
        return best_match
    return None


selected_filters = {}


def on_click_show_films(message):
    films = get_filtered_films(selected_filters)
    if films:
        bot.send_message(message.chat.id, "Вот фильмы по выбранным критериям:")
        show_next_films(message, films, 0)
    else:
        bot.send_message(message.chat.id, "Фильмов по выбранным критериям не найдено.")
        show_main_menu(message)
    selected_filters.clear()


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
        country_id = get_country_id(filters['Страна'])
        if country_id:
            conditions.append("id_country = %s")
            params.append(country_id)

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
        actor_film_ids = get_actor_film_ids(filters['Актеры'])
        film_ids = set(actor_film_ids) if film_ids is None else film_ids & set(actor_film_ids)

    if 'Жанр' in filters:
        genre_film_ids = get_genre_film_ids(filters['Жанр'])
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
        bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
        return
    with conn:
        cursor.execute(query, params)
            result = cursor.fetchall()
            films = [row['name'] for row in result]
            if film_ids is not None:
                with_ids = get_film_ids_by_names(films, conn)
                films = [name for name, fid in with_ids if fid in film_ids]
            return films


def get_country_id(name):
    conn = connect_db()
    if not conn:
        bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
        return
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM countries WHERE name = %s", (name,))
            row = cursor.fetchone()
            return row['id'] if row else None


def get_age_limit_id(label):
    conn = connect_db()
    if not conn:
        bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
        return
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM age_limits WHERE label = %s", (label,))
            row = cursor.fetchone()
            return row['id'] if row else None


def get_director_id(surname):
    surname = surname.strip().lower()
    conn = connect_db()
    if not conn:
        bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
        return
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM directors WHERE LOWER(surname) = %s", (surname,))
            row = cursor.fetchone()
            return row['id'] if row else None


def get_actor_film_ids(surname):
    surname = surname.strip().lower()
    conn = connect_db()
    if not conn:
        bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
        return
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM actors WHERE LOWER(surname) = %s", (surname,))
            actor_row = cursor.fetchone()
            if not actor_row:
                return []
            actor_id = actor_row['id']

            cursor.execute("SELECT id_film FROM cast_films WHERE id_actor = %s", (actor_id,))
            result = cursor.fetchall()
            return [row['id_film'] for row in result]


def get_genre_film_ids(genre):
    conn = connect_db()
    if not conn:
        bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
        return
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM genres WHERE name = %s", (genre,))
            genre_row = cursor.fetchone()
            if not genre_row:
                return []
            genre_id = genre_row['id']

            cursor.execute("SELECT id_film FROM genre_films WHERE id_genre = %s", (genre_id,))
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
                INSERT INTO ratings (user_id, id_film, rating)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE rating = VALUES(rating)
            """, (user_id, film_id, rating))
        connection.commit()
    except Exception as e:
        log_error(f"Ошибка при сохранении оценки: user_id={user_id}, film_id={film_id}, rating={rating}, ошибка: {str(e)}")


def get_rating_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row(*(types.KeyboardButton(str(i)) for i in range(1, 4)))
    markup.row(*(types.KeyboardButton(str(i)) for i in range(4, 6)))
    markup.row(types.KeyboardButton('Не хочу оценивать'))
    return markup


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
                else:
                    bot.send_message(message.chat.id, 'Фильм не найден в базе данных.')
                    log_error(f"Фильм не найден в базе данных: '{film_name}'")
        else:
            bot.send_message(message.chat.id, 'Пожалуйста, введите число от 1 до 5.')
            rate_film(message, film_name)
    except ValueError:
        bot.send_message(message.chat.id, 'Пожалуйста, введите число от 1 до 5.')
        bot.register_next_step_handler(message, lambda msg: get_rating(msg, film_name))


def get_rating_random(message, film_name):
    if message.text == 'Не хочу оценивать':
        bot.send_message(message.chat.id, 'Спасибо! Вы не оценили фильм.')
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
            bot.send_message(message.chat.id, 'Ошибка подключения к базе данных. Попробуйте позже.')
            return
        with conn:
            df = pd.read_sql("SELECT user_id, id_film, rating FROM ratings", conn)

            if df.empty:
                return []

            user_film_matrix = df.pivot_table(index='user_id', columns='id_film', values='rating').fillna(0)

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
                return [row['name'] for row in rows]
    except Exception as e:
        log_error(f"Ошибка при формировании рекомендаций: {str(e)}")
        return []


@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton('Подборка фильмов')
    btn2 = types.KeyboardButton('Случайный фильм')
    btn3 = types.KeyboardButton('Рекомендации')
    btn4 = types.KeyboardButton('Завершить работу')
    btn5 = types.KeyboardButton('Оставить отзыв на работу бота')
    markup.row(btn1, btn2)
    markup.row(btn3, btn4)
    markup.row(btn5)
    bot.send_message(message.chat.id, f'Привет, {message.from_user.username}! Выбери, что ты хочешь сделать 👇🏻', reply_markup=markup)
    bot.register_next_step_handler(message, on_click)


def on_click(message):
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
    btn5 = types.KeyboardButton('Оставить отзыв на работу бота')
    markup.row(btn1, btn2)
    markup.row(btn3, btn4)
    markup.row(btn5)
    bot.send_message(message.chat.id, 'Что бы вы хотели сделать дальше?', reply_markup=markup)
    bot.register_next_step_handler(message, on_click)


def save_feedback(message):
    feedback = message.text
    with open('feedback.txt', 'a', encoding='utf-8') as f:
        f.write(f"{message.from_user.username}: {feedback}\n")
    bot.send_message(message.chat.id, 'Спасибо за ваш отзыв!')
    show_main_menu(message)


def get_recommendations():
    recommendations = []
    try:
        with open(r'C:\Users\Даша\Desktop\2 курс\pythonProject\recommendations.csv', newline='', encoding='cp1251') as csvfile:
            reader = csv.reader(csvfile, delimiter=';')
            for row in reader:
                if row:  # Проверка, что строка не пустая
                    recommendations.append(row[0])
    except Exception as e:
        print(f"Ошибка при чтении файла: {e}")
    return recommendations


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    bot.send_message(message.chat.id, 'Неизвестная команда. Пожалуйста, выберите одну из предложенных опций.')
    show_main_menu(message)


def filter_choice(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton('Год')
    btn2 = types.KeyboardButton('Возрастное ограничение')
    btn3 = types.KeyboardButton('Жанр')
    btn4 = types.KeyboardButton('Режиссер')
    btn5 = types.KeyboardButton('Страна')
    btn6 = types.KeyboardButton('Длительность')
    btn7 = types.KeyboardButton('Рейтинг')
    btn8 = types.KeyboardButton('Актеры')
    btn_done = types.KeyboardButton('Показать фильмы')
    btn_back = types.KeyboardButton('Назад')
    markup.row(btn1, btn2, btn3)
    markup.row(btn4, btn5, btn6)
    markup.row(btn7, btn8, btn_back)
    markup.row(btn_done)
    if selected_filters:
        bot.send_message(message.chat.id, 'Выберите следующий критерий или нажмите "Показать фильмы".', reply_markup=markup)
    else:
        bot.send_message(message.chat.id, 'Выберите критерий, который важен вам при выборе фильма 👇🏻', reply_markup=markup)
    bot.register_next_step_handler(message, on_click_filter)


def on_click_filter(message):
    if message.text == 'Назад':
        selected_filters.popitem()  # Удалить последний добавленный фильтр
        filter_choice(message)  # Вернуться к выбору фильтра
        return
    filter_type = message.text
    if filter_type not in selected_filters:
        selected_filters[filter_type] = None
    if message.text == 'Показать фильмы':
        on_click_show_films(message)
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
        btn1 = types.InlineKeyboardButton('ниже 3.0', callback_data='rating_1')
        btn2 = types.InlineKeyboardButton('3.0 - 4.9', callback_data='rating_2')
        btn3 = types.InlineKeyboardButton('5.0 - 6.9', callback_data='rating_3')
        btn4 = types.InlineKeyboardButton('7.0 - 7.9', callback_data='rating_4')
        btn5 = types.InlineKeyboardButton('8.0 - 8.9', callback_data='rating_5')
        btn6 = types.InlineKeyboardButton('9.0 - 10.0', callback_data='rating_6')
        markup_inline.add(btn1, btn2, btn3, btn4, btn5, btn6)
        bot.reply_to(message, 'Какой рейтинг должен быть у фильма?', reply_markup=markup_inline)
    elif message.text == 'Актеры':
        bot.send_message(message.chat.id, 'Введи фамилию актера, фильм с которым хотел(-а) бы посмотреть')
        bot.register_next_step_handler(message, on_click_actor)
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
    selected_filters['Год'] = (year1, year2)
    filter_choice(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('duration_'))
def on_click_duration(call):
    duration_ranges = {
        'duration_1': (0, 59),
        'duration_2': (60, 89),
        'duration_3': (90, 119),
        'duration_4': (120, 500),
    }
    dur1, dur2 = duration_ranges[call.data]
    selected_filters['Длительность'] = (dur1, dur2)
    filter_choice(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('rating_'))
def on_click_rating(call):
    rating_ranges = {
        'rating_1': (0, 2.9),
        'rating_2': (3.0, 4.9),
        'rating_3': (5.0, 6.9),
        'rating_4': (7.0, 7.9),
        'rating_5': (8.0, 8.9),
        'rating_6': (9.0, 10.0),
    }
    rating1, rating2 = rating_ranges[call.data]
    selected_filters['Рейтинг'] = (rating1, rating2)
    filter_choice(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('country_'))
def on_click_country(call):
    country = call.data.split('_')[1]
    selected_filters['Страна'] = country
    filter_choice(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('limit_'))
def on_click_age_limit(call):
    age_limit = call.data.split('_')[1]
    selected_filters['Возрастное ограничение'] = age_limit
    filter_choice(call.message)


def on_click_director(message):
    director = message.text
    selected_filters['Режиссер'] = director
    filter_choice(message)


def on_click_actor(message):
    actor = message.text
    selected_filters['Актеры'] = actor
    filter_choice(message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('genre_'))
def on_click_genre(call):
    genre = call.data.split('_')[1]
    selected_filters['Жанр'] = genre
    filter_choice(call.message)


bot.polling(none_stop=True)