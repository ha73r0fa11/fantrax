"""Telegram-бот с отчётами Fantrax. Только стандартная библиотека.

Запуск:  set BOT_TOKEN=...   (PowerShell: $env:BOT_TOKEN="...")  затем  python bot.py
Данные берутся из папки data/ (готовит update_data.py).
"""

import glob
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
TOKEN = os.environ.get("BOT_TOKEN", "")
# Необязательно: id чатов/пользователей через запятую, которым разрешён доступ
ALLOWED = {int(x) for x in os.environ.get("ALLOWED_IDS", "").replace(" ", "").split(",") if x}

TOUR_BLOCKS = [
    ("lead", "🏆 Лидер/Нелидер"),
    ("players", "⭐ Лучшие футболисты"),
    ("king", "👑 Король скамейки"),
    ("super", "🔥 Супертопы"),
    ("free", "🆓 Свободные агенты"),
]
SEASON_BLOCKS = [
    ("records", "🏅 Рекорды"),
    ("table", "📊 Таблица менеджеров"),
    ("team", "🌟 Сборная сезона"),
    ("top10", "🔟 10 лучших выступлений"),
    ("perf", "🥇 Лучший перформанс менеджеров"),
]
# какой заголовок "### ..." в отчёте соответствует блоку
SECTION_KEYS = {
    "players": "Лучшие футболисты",
    "super": "Супертопы",
    "free": "свободные агенты",
    "table": "Таблица менеджеров",
    "team": "Сборная сезона",
    "top10": "10 лучших",
    "perf": "Лучший перформанс",
}


# ---------- работа с Telegram API ----------
def api(method, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.loads(r.read().decode("utf-8"))["result"]
    except urllib.error.HTTPError as e:
        print("Ошибка API:", e.read().decode("utf-8", "replace"), file=sys.stderr)
        return None


def keyboard(rows):
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


# ---------- данные ----------
def available_tours():
    nums = []
    for p in glob.glob(os.path.join(DATA, "tour_*.md")):
        m = re.search(r"tour_(\d+)\.md$", p)
        if m:
            nums.append(int(m.group(1)))
    return sorted(nums)


def read(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def split_sections(text):
    """Возвращает (вступление, [(заголовок, текст), ...]) по заголовкам '### '."""
    intro, sections, cur = [], [], None
    for line in text.splitlines():
        if line.startswith("### "):
            cur = [line[4:], []]
            sections.append(cur)
        elif cur is None:
            intro.append(line)
        else:
            cur[1].append(line)
    return "\n".join(intro), [(h, "\n".join(b)) for h, b in sections]


def tour_block(tour, key):
    text = read(f"tour_{tour}.md")
    if text is None:
        return "Нет данных по этому туру."
    tour_part = text.split("#статистикасезона")[0]
    intro, sections = split_sections(tour_part)
    if key == "lead":
        return "\n".join(l for l in intro.splitlines() if l.startswith("- "))
    if key == "king":
        for _, body in sections:
            for l in body.splitlines():
                if "Король скамейки" in l:
                    return l
        return "Нет данных."
    for head, body in sections:
        if SECTION_KEYS[key].lower() in head.lower():
            if key == "players":
                body = "\n".join(l for l in body.splitlines() if "Король скамейки" not in l)
            return body.strip()
    return "Нет данных."


def season_block(key):
    text = read("season.md")
    if text is None:
        return "Нет данных по сезону."
    intro, sections = split_sections(text)
    if key == "records":
        return "\n".join(l for l in intro.splitlines() if l.startswith("- "))
    for head, body in sections:
        if SECTION_KEYS[key].lower() in head.lower():
            return body.strip()
    return "Нет данных."


# ---------- оформление ----------
def render(md):
    """Markdown-фрагмент -> HTML для Telegram (таблицы в <pre>)."""
    out, table = [], []

    def flush():
        if not table:
            return
        rows = [[c.strip() for c in r.strip("|").split("|")] for r in table]
        rows = [r for r in rows if not all(re.fullmatch(r":?-{3,}:?", c) for c in r)]
        widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
        lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
        out.append("<pre>" + html.escape("\n".join(lines), quote=False) + "</pre>")
        table.clear()

    for line in md.splitlines():
        if line.startswith("|"):
            table.append(line)
            continue
        flush()
        if line.strip():
            out.append(re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(line, quote=False)))
    flush()
    return "\n".join(out) or "Нет данных."


def chunks(text, limit=3800):
    parts, cur = [], ""
    for piece in text.split("\n"):
        if len(cur) + len(piece) + 1 > limit and cur:
            parts.append(cur)
            cur = ""
        cur += piece + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


# ---------- меню ----------
def main_menu():
    return "Выберите отчёт:", keyboard([[("📅 Отчет по туру", "m:tours")], [("🏆 Отчет по сезону", "m:season")]])


def tours_menu():
    nums = available_tours()
    if not nums:
        return "Данных по турам пока нет.", keyboard([[("⬅️ Назад", "m:main")]])
    btns = [(f"Тур {n}", f"t:{n}") for n in nums]
    rows = [btns[i : i + 4] for i in range(0, len(btns), 4)]
    rows.append([("⬅️ Назад", "m:main")])
    return "Выберите тур:", keyboard(rows)


def tour_menu(n):
    rows = [[(title, f"tb:{n}:{key}")] for key, title in TOUR_BLOCKS]
    rows.append([("⬅️ К турам", "m:tours")])
    return f"Тур {n}. Что показать?", keyboard(rows)


def season_menu():
    rows = [[(title, f"sb:{key}")] for key, title in SEASON_BLOCKS]
    rows.append([("⬅️ Назад", "m:main")])
    return "Отчёт по сезону. Что показать?", keyboard(rows)


def send_menu(chat_id, menu, message_id=None):
    text, markup = menu
    if message_id:
        api("editMessageText", chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
    else:
        api("sendMessage", chat_id=chat_id, text=text, reply_markup=markup)


def send_block(chat_id, md, back_menu):
    parts = chunks(render(md))
    for p in parts:
        api("sendMessage", chat_id=chat_id, text=p, parse_mode="HTML")
    send_menu(chat_id, back_menu)


def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    mid = cb["message"]["message_id"]
    data = cb["data"]
    api("answerCallbackQuery", callback_query_id=cb["id"])
    kind, *rest = data.split(":")
    if data == "m:main":
        send_menu(chat_id, main_menu(), mid)
    elif data == "m:tours":
        send_menu(chat_id, tours_menu(), mid)
    elif data == "m:season":
        send_menu(chat_id, season_menu(), mid)
    elif kind == "t":
        send_menu(chat_id, tour_menu(int(rest[0])), mid)
    elif kind == "tb":
        n, key = int(rest[0]), rest[1]
        send_block(chat_id, tour_block(n, key), tour_menu(n))
    elif kind == "sb":
        send_block(chat_id, season_block(rest[0]), season_menu())


def handle_update(u):
    if "callback_query" in u:
        cb = u["callback_query"]
        if ALLOWED and cb["from"]["id"] not in ALLOWED and cb["message"]["chat"]["id"] not in ALLOWED:
            return
        handle_callback(cb)
    elif "message" in u:
        msg = u["message"]
        if ALLOWED and msg["from"]["id"] not in ALLOWED and msg["chat"]["id"] not in ALLOWED:
            return
        if msg.get("text", "").startswith(("/start", "/menu")):
            send_menu(msg["chat"]["id"], main_menu())


def main():
    if not TOKEN:
        sys.exit("Не задана переменная окружения BOT_TOKEN")
    print("Бот запущен. Остановка: Ctrl+C", file=sys.stderr)
    offset = None
    while True:
        try:
            params = {"timeout": 50, "allowed_updates": ["message", "callback_query"]}
            if offset:
                params["offset"] = offset
            for u in api("getUpdates", **params) or []:
                offset = u["update_id"] + 1
                try:
                    handle_update(u)
                except Exception as e:
                    print("Ошибка обработки:", e, file=sys.stderr)
        except Exception as e:
            print("Сбой связи, повтор через 5 с:", e, file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    main()
