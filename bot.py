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
    ("full", "📋 Полная статистика тура"),
]
SEASON_BLOCKS = [
    ("records", "🏅 Рекорды"),
    ("table", "📊 Таблица менеджеров"),
    ("team", "🌟 Сборная сезона"),
    ("top10", "🔟 10 лучших выступлений"),
    ("perf", "🥇 Лучший перформанс менеджеров"),
    ("full", "📋 Полная статистика сезона"),
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


def full_text(md):
    """Весь отчёт без хештегов и общих заголовков (их заменяет заголовок сообщения)."""
    lines = [l for l in md.splitlines() if not l.startswith(("#статистика", "# ", "## "))]
    return "\n".join(lines).strip()


def tour_block(tour, key):
    text = read(f"tour_{tour}.md")
    if text is None:
        return "Нет данных по этому туру."
    tour_part = text.split("#статистикасезона")[0]
    intro, sections = split_sections(tour_part)
    if key == "full":
        return full_text(tour_part)
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
    if key == "full":
        return full_text(text)
    if key == "records":
        return "\n".join(l for l in intro.splitlines() if l.startswith("- "))
    for head, body in sections:
        if SECTION_KEYS[key].lower() in head.lower():
            return body.strip()
    return "Нет данных."


# ---------- оформление ----------
def row_text(r):
    """Строка таблицы -> читаемая строка с выделенным именем (Telegram не умеет таблицы)."""
    esc = lambda s: html.escape(s, quote=False)
    name = esc(r.get("Игрок") or r.get("Менеджер") or "")
    prefix = f"{esc(r['#'])}. " if "#" in r else ""
    if "Номинация" in r:
        prefix = f"{esc(r['Номинация'])}: "
    if "Сумма FPts" in r:
        return (
            f"{prefix}<b>{name}</b> — {esc(r['Очки'])} очк. ({esc(r['В-Н-П'])})\n"
            f"      сумма {esc(r['Сумма FPts'])} · голы {esc(r['Голы'])} · пасы {esc(r['Пасы'])} · Г+П {esc(r['Г+П'])}"
        )
    owner = r.get("Команда") or r.get("У кого") or ""
    info = ", ".join(esc(x) for x in (r.get("Поз."), r.get("Клуб"), owner) if x)
    line = f"{prefix}<b>{name}</b>" + (f" ({info})" if info else "")
    if "Очки" in r:
        line += f" — <b>{esc(r['Очки'])}</b>"
    if "Тур" in r:
        line += f", тур {esc(r['Тур'])}"
    return line


def render(md):
    """Markdown-фрагмент -> HTML для Telegram (таблицы в <pre>)."""
    out, table = [], []

    def flush():
        if not table:
            return
        rows = [[c.strip() for c in r.strip("|").split("|")] for r in table]
        rows = [r for r in rows if not all(re.fullmatch(r":?-{3,}:?", c) for c in r)]
        head = rows[0]
        lines = [row_text(dict(zip(head, r))) for r in rows[1:]]
        out.append("\n".join(lines))
        table.clear()

    for line in md.splitlines():
        if line.startswith("|"):
            table.append(line)
            continue
        flush()
        if line.startswith("### "):
            out.append(f"<b>{html.escape(line[4:], quote=False)}</b>")
        elif line.strip():
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


# ---------- меню (кнопки внизу экрана) ----------
BTN_TOUR, BTN_SEASON = "📅 Отчет по туру", "🏆 Отчет по сезону"
BTN_BACK, BTN_TO_TOURS = "⬅️ Назад", "⬅️ К турам"
STATE = {}  # chat_id -> {"screen": "main"|"tours"|"tour"|"season", "tour": N}


def reply_keyboard(rows):
    return {"keyboard": [[{"text": t} for t in row] for row in rows], "resize_keyboard": True, "is_persistent": True}


def show(chat_id, screen, text, rows, tour=None):
    STATE[chat_id] = {"screen": screen, "tour": tour}
    api("sendMessage", chat_id=chat_id, text=text, reply_markup=reply_keyboard(rows))


def show_main(chat_id):
    show(chat_id, "main", "Выберите отчёт:", [[BTN_TOUR], [BTN_SEASON]])


def show_tours(chat_id):
    nums = available_tours()
    if not nums:
        return show(chat_id, "tours", "Данных по турам пока нет.", [[BTN_BACK]])
    btns = [f"Тур {n}" for n in nums]
    rows = [btns[i : i + 4] for i in range(0, len(btns), 4)] + [[BTN_BACK]]
    show(chat_id, "tours", "Выберите тур:", rows)


def show_tour(chat_id, n):
    rows = [[title] for _, title in TOUR_BLOCKS] + [[BTN_TO_TOURS]]
    show(chat_id, "tour", f"Тур {n}. Что показать?", rows, n)


def show_season(chat_id):
    rows = [[title] for _, title in SEASON_BLOCKS] + [[BTN_BACK]]
    show(chat_id, "season", "Отчёт по сезону. Что показать?", rows)


def send_block(chat_id, title, md):
    # Rich messages (Bot API 10.3+) показывают настоящие таблицы; при ошибке - запасной текстовый вывод
    if md.strip() and api("sendRichMessage", chat_id=chat_id, rich_message={"markdown": f"## {title}\n\n{md}"}) is not None:
        return
    for p in chunks(f"<b>{html.escape(title, quote=False)}</b>\n\n{render(md)}"):
        api("sendMessage", chat_id=chat_id, text=p, parse_mode="HTML")


def handle_text(chat_id, text):
    state = STATE.get(chat_id, {"screen": "main", "tour": None})
    screen = state["screen"]
    if text in ("/start", "/menu") or text.startswith(("/start@", "/menu@")) or text == BTN_BACK and screen in ("tours", "season"):
        return show_main(chat_id)
    if text == BTN_TOUR:
        return show_tours(chat_id)
    if text == BTN_SEASON:
        return show_season(chat_id)
    if text == BTN_TO_TOURS:
        return show_tours(chat_id)
    m = re.fullmatch(r"Тур (\d+)", text)
    if m and int(m.group(1)) in available_tours():
        return show_tour(chat_id, int(m.group(1)))
    if screen == "tour" and state["tour"]:
        for key, title in TOUR_BLOCKS:
            if text == title:
                n = state["tour"]
                return send_block(chat_id, f"{title} - Тур {n}", tour_block(n, key))
    if screen == "season":
        for key, title in SEASON_BLOCKS:
            if text == title:
                return send_block(chat_id, title, season_block(key))


def handle_update(u):
    msg = u.get("message")
    if not msg or "text" not in msg:
        return
    if ALLOWED and msg["from"]["id"] not in ALLOWED and msg["chat"]["id"] not in ALLOWED:
        return
    handle_text(msg["chat"]["id"], msg["text"].strip())

def main():
    if not TOKEN:
        sys.exit("Не задана переменная окружения BOT_TOKEN")
    print("Бот запущен. Остановка: Ctrl+C", file=sys.stderr)
    offset = None
    while True:
        try:
            params = {"timeout": 50, "allowed_updates": ["message"]}
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
