import telebot
from telebot import types
import requests
from bs4 import BeautifulSoup
from io import BytesIO
import pandas
import os

bot = telebot.TeleBot(os.getenv("BOT_TOKEN"))

# память пользователей
user_data = {}

@bot.message_handler(commands=['start'])
def start(message):
    name = message.from_user.first_name

    bot.send_message(
        message.chat.id,
        f"Привет, {name}!\n"
        "Отправь мне картинку, и я найду похожие изображения"
    )

# превращаем id в ссылку
def get_image_url(file_id):
    file_info = bot.get_file(file_id)
    file_path = file_info.file_path
    return f"https://api.telegram.org/file/bot{bot.token}/{file_path}"

# поиск
def search_image(image_url):
    url = f"https://yandex.ru/images/search?rpt=imageview&url={image_url}"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        return []
    
    soup = BeautifulSoup(r.text, "html.parser")

    results = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"]

        if not href.startswith("http"):
            continue

        low = href.lower() 

        if any(x in low for x in ["passport", "login", "auth", "yandex.ru/support", "search", "support", "help", "feedback", "legal", "terms"]):
            continue

        # фильтр маркетплейсов
        if "ozon.ru" in low:
            results.append({"url": href, "type": "market"}) 

        elif "wildberries.ru" in low or "wb.ru" in low:
            results.append({"url": href, "type": "market"})

        elif "market.yandex.ru" in low:
            results.append({"url": href, "type": "market"})

        # обычные сайты
        elif "yandex" in low or "google" in low:
            results.append({"url": href, "type": "general"})


    # убираем дубли
    unique = []
    seen = set()

    for r_ in results:
        if r_["url"] not in seen:
            seen.add(r_["url"])
            unique.append(r_)

    return unique[:30]

# обработка фото
@bot.message_handler(content_types=['photo'])
def get_photo(message):
    file_id = message.photo[-1].file_id

    image_url = get_image_url(file_id) 
    results = search_image(image_url) 

    # сохраняем
    user_data[message.from_user.id] = {
        "results": results,
        "page": 0,
        "filter": "all"
    }

    # сразу показываем результат
    show_results(message.chat.id, None, message.from_user.id)

# результат
def show_results(chat_id, message_id, user_id):
    data = user_data[user_id]

    results = data["results"] 
    page = data["page"]
    filter_type = data.get("filter", "all") 

    #фильтр
    if filter_type == "general": 
        results = [r for r in results if r["type"] == "general"] 
    elif filter_type == "market":
        results = [r for r in results if r["type"] == "market"] 

    per_page = 5 # кол-во ссылок на странице
    total_pages = max(1, (len(results) + per_page - 1) // per_page)

    start = page * per_page
    end = start + per_page

    page_results = results[start:end]

    if not page_results:
        text = "Ничего больше не найдено"
    else:
        text = f" Страница {page + 1}/{total_pages}\n\n" 

        for i, r in enumerate(page_results, start=1): 
            from html import escape
            text += f'{start + i}. <a href="{escape(r["url"])}">Ссылка {start + i}</a>\n\n'

#кнопки
    markup = types.InlineKeyboardMarkup()

    btn_next = types.InlineKeyboardButton("Вперёд ➡️", callback_data="next")

    if page > 0:
        btn_prev = types.InlineKeyboardButton("⬅️ Назад", callback_data="prev")
        markup.row(btn_prev, btn_next)
    else:
        markup.row(btn_next)

    btn_general = types.InlineKeyboardButton("Общие результаты", callback_data="general")
    btn_market = types.InlineKeyboardButton("Маркетплейсы", callback_data="market")
    markup.row(btn_general, btn_market)

    btn_excel = types.InlineKeyboardButton("Excel", callback_data="excel")
    markup.row(btn_excel)

    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    user_id = call.from_user.id

    if user_id not in user_data:
        return

    data = user_data[user_id]

    if call.data == "show":
        show_results(call.message.chat.id, call.message.message_id, user_id)

    elif call.data == "next":
        data["page"] += 1
        show_results(call.message.chat.id, call.message.message_id, user_id)

    elif call.data == "prev":
        if data["page"] > 0:
            data["page"] -= 1
        show_results(call.message.chat.id, call.message.message_id, user_id)


    elif call.data == "general":
        data["filter"] = "general"
        data["page"] = 0
        show_results(call.message.chat.id, call.message.message_id, user_id)

    elif call.data == "market":
        data["filter"] = "market"
        data["page"] = 0
        show_results(call.message.chat.id, call.message.message_id, user_id)

    # CSV
    elif call.data == "excel":
        urls = [r["url"] for r in data["results"] if r["type"] == data.get("filter", "all")]

        df = pandas.DataFrame({"Ссылки": urls})

        file = BytesIO()
        df.to_csv(file, index=False, encoding="utf-8-sig") 
        file.seek(0)

        bot.send_document(call.message.chat.id, file, visible_file_name="Файл Excel с результатами.csv") 

bot.polling(none_stop=True)