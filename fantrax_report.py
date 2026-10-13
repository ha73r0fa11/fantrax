"""Отчёт по лиге Fantrax за тур и сезон (туры 1..N).

    python fantrax_report.py --tour 1
    python fantrax_report.py --tour 5 --out-file tour5.md

Используются только публичные данные лиги, авторизация не нужна.
"""

import argparse
import json
import re
import sys
import time
import urllib.request

CLIENT_VERSION = "187.0.1"
SEASON_CODE = "SEASON_926_BY_PERIOD"
POS_NAMES = {"G": "вратарь", "D": "защитник", "M": "полузащитник", "F": "нападающий"}


class Fantrax:
    def __init__(self, league_id):
        self.league_id = league_id
        self.url = f"https://www.fantrax.com/fxpa/req?leagueId={league_id}"

    def query(self, method, data):
        body = json.dumps(
            {
                "msgs": [{"method": method, "data": data}],
                "uiv": 3,
                "refUrl": f"https://www.fantrax.com/fantasy/league/{self.league_id}/standings",
                "dt": "DESKTOP",
                "at": "WEB",
                "tz": "Europe/Moscow",
                "v": CLIENT_VERSION,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
        )
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("pageError"):
                    raise RuntimeError(payload["pageError"].get("code"))
                return payload["responses"][0]["data"]
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2)


def num(value):
    if value is None or str(value) == "":
        return 0.0
    return float(str(value).replace(",", ""))


def fmt(x):
    return f"{x:.2f}"


def whole(x):
    return int(x) if float(x).is_integer() else x


def primary_pos(pos):
    return re.split(r"[,/ ]", pos or "")[0]


def col(header, name):
    return header.index(name) if name in header else -1


def cell(row, index):
    return row["cells"][index]["content"] if 0 <= index < len(row["cells"]) else None


def top(items, key, smallest=False):
    items = list(items)
    if not items:
        return []
    values = [key(x) for x in items]
    target = min(values) if smallest else max(values)
    return [x for x in items if key(x) == target]


def by_points_desc(*tie_breakers):
    return lambda x: (-x["fpts"], *(f(x) for f in tie_breakers))


def name_key(x):
    return x["name"].casefold()


def owner_text(x):
    if not x["owner"]:
        return "свободный агент"
    if x["active"]:
        return x["owner"]
    return f"{x['owner']} (скамейка)"


def load_data(api, tour):
    standings = {}
    team_name = {}
    for p in range(1, tour + 1):
        d = api.query("getStandings", {"leagueId": api.league_id, "timeframeType": "BY_PERIOD", "period": str(p)})
        table = d["tableList"][0]
        header = [c["shortName"] for c in table["header"]["cells"]]
        iw, idr, il, ip, iff = (col(header, n) for n in ("W", "D", "L", "Points", "FPtsF"))
        rows = []
        for r in table["rows"]:
            team = r["fixedCells"][1]
            team_name[team["teamId"]] = team["content"]
            rows.append(
                {
                    "team_id": team["teamId"],
                    "w": num(cell(r, iw)),
                    "d": num(cell(r, idr)),
                    "l": num(cell(r, il)),
                    "pts": num(cell(r, ip)),
                    "fpts": num(cell(r, iff)),
                }
            )
        standings[p] = rows
        print(f"Тур {p}: таблица загружена", file=sys.stderr)
    team_ids = [r["team_id"] for r in standings[1]]

    roster = []
    owner_of = {}
    for p in range(1, tour + 1):
        for tid in team_ids:
            base = {
                "leagueId": api.league_id,
                "teamId": tid,
                "period": str(p),
                "view": "STATS",
                "seasonOrProjection": SEASON_CODE,
                "timeframeTypeCode": "BY_PERIOD",
            }
            d = api.query("getTeamRosterInfo", base)
            for tb in d["tables"]:
                header = [c["shortName"] for c in tb["header"]["cells"]]
                iff, ig, ia = col(header, "FPts"), col(header, "G"), col(header, "AT")
                for row in tb["rows"]:
                    scorer = row.get("scorer")
                    if not scorer or not scorer.get("scorerId"):
                        continue
                    g, a = num(cell(row, ig)), num(cell(row, ia))
                    entry = {
                        "tour": p,
                        "team_id": tid,
                        "team": team_name[tid],
                        "id": scorer["scorerId"],
                        "name": scorer["name"],
                        "club": scorer.get("teamShortName"),
                        "pos": primary_pos(scorer.get("posShortNames")),
                        "active": row.get("statusId") == "1",
                        "fpts": num(cell(row, iff)),
                        "g": g,
                        "a": a,
                    }
                    roster.append(entry)
                    owner_of[(p, entry["id"])] = entry
        print(f"Тур {p}: составы загружены", file=sys.stderr)

    players = []
    for p in range(1, tour + 1):
        page = 1
        while True:
            d = api.query(
                "getPlayerStats",
                {
                    "leagueId": api.league_id,
                    "statusOrTeamFilter": "ALL",
                    "seasonOrProjection": SEASON_CODE,
                    "timeframeTypeCode": "BY_PERIOD",
                    "transactionPeriod": str(p),
                    "pageNumber": str(page),
                },
            )
            header = [c["shortName"] for c in d["tableHeader"]["cells"]]
            iff = col(header, "FPts")
            for r in d["statsTable"]:
                scorer = r["scorer"]
                own = owner_of.get((p, scorer["scorerId"]))
                players.append(
                    {
                        "tour": p,
                        "id": scorer["scorerId"],
                        "name": scorer["name"],
                        "club": scorer.get("teamShortName"),
                        "pos": primary_pos(scorer.get("posShortNames")),
                        "fpts": num(cell(r, iff)),
                        "owner": own["team"] if own else None,
                        "active": own["active"] if own else False,
                    }
                )
            page += 1
            if page > d["paginatedResultSet"]["totalNumPages"]:
                break
        print(f"Тур {p}: игроки загружены", file=sys.stderr)

    return standings, team_name, team_ids, roster, players


def validate(standings, team_name, roster, tour):
    ok = True
    for p in range(1, tour + 1):
        for s in standings[p]:
            total = sum(x["fpts"] for x in roster if x["tour"] == p and x["team_id"] == s["team_id"] and x["active"])
            if abs(total - s["fpts"]) > 0.01:
                ok = False
                print(
                    f"ПРЕДУПРЕЖДЕНИЕ: тур {p}, {team_name[s['team_id']]}: состав {fmt(total)} != таблица {fmt(s['fpts'])}",
                    file=sys.stderr,
                )
    if ok:
        print("Проверка: очки основных составов совпадают с таблицей лиги во всех турах", file=sys.stderr)


def build_report(tour, standings, team_name, team_ids, roster, players, super_top):
    out = []

    def line(s=""):
        out.append(s)

    def table(head, rows):
        line("| " + " | ".join(head) + " |")
        line("|" + "|".join("---" for _ in head) + "|")
        for r in rows:
            line("| " + " | ".join(str(c) for c in r) + " |")
        line()

    def nomination_rows(items, with_team):
        rows = []
        best = max((x["fpts"] for x in items), default=None)
        for pos in "GDMF":
            for b in top([x for x in items if x["pos"] == pos], lambda x: x["fpts"]):
                star = "⭐ " if b["fpts"] == best else ""
                row = [f"{star}Лучший {POS_NAMES[pos]}", b["name"], b["pos"], b["club"]]
                rows.append(row + ([b["team"]] if with_team else []) + [fmt(b["fpts"])])
        return rows

    cur = [x for x in players if x["tour"] == tour]
    cur_roster = [x for x in roster if x["tour"] == tour]
    cur_teams = [{"team": team_name[s["team_id"]], "fpts": s["fpts"]} for s in standings[tour]]

    line("#статистикатура")
    line()
    line(f"# Fantrax: отчёт по туру {tour}")
    line()
    line(f"## Тур {tour}")
    line()
    lead = top(cur_teams, lambda x: x["fpts"])
    last = top(cur_teams, lambda x: x["fpts"], smallest=True)
    line("- 🏆 **Лидер тура:** " + ", ".join(f"**{x['team']}** ({fmt(x['fpts'])})" for x in lead))
    line("- 📉 **Нелидер тура:** " + ", ".join(f"**{x['team']}** ({fmt(x['fpts'])})" for x in last))
    line()

    line("### Лучшие футболисты тура (основной состав)")
    line()
    active = [x for x in cur_roster if x["active"]]
    table(["Номинация", "Игрок", "Поз.", "Клуб", "Команда", "Очки"], nomination_rows(active, True))

    kings = top([x for x in cur_roster if not x["active"]], lambda x: x["fpts"])
    line(
        "👑 **Король скамейки:** "
        + "; ".join(f"{k['team']} ({k['name']} ({k['pos']}, {k['club']}), {fmt(k['fpts'])})" for k in kings)
    )
    line()

    line(f"### 🔥 Супертопы ({whole(super_top)}+ очков за тур)")
    line()
    supers = sorted((x for x in cur if x["fpts"] >= super_top), key=by_points_desc(name_key))
    if supers:
        table(
            ["Игрок", "Поз.", "Клуб", "Команда", "Очки"],
            [[x["name"], x["pos"], x["club"], owner_text(x), fmt(x["fpts"])] for x in supers],
        )
    else:
        line("_Никто не набрал нужное количество очков._")
        line()

    line("### Лучшие свободные агенты тура (не были ни в одной команде)")
    line()
    free = [x for x in cur if not x["owner"]]
    table(["Номинация", "Игрок", "Поз.", "Клуб", "Очки"], nomination_rows(free, False))

    line("#статистикасезона")
    line()
    line(f"## Сезон (туры 1–{tour})")
    line()

    managers = []
    for tid in team_ids:
        results = [next(r for r in standings[p] if r["team_id"] == tid) for p in range(1, tour + 1)]
        mine = [x for x in roster if x["team_id"] == tid and x["active"]]
        run = best = best_from = best_to = start = 0
        for p, r in enumerate(results, start=1):
            if r["l"] == 0:
                if run == 0:
                    start = p
                run += 1
                if run > best:
                    best, best_from, best_to = run, start, p
            else:
                run = 0
        g, a = sum(x["g"] for x in mine), sum(x["a"] for x in mine)
        managers.append(
            {
                "team": team_name[tid],
                "w": sum(r["w"] for r in results),
                "d": sum(r["d"] for r in results),
                "l": sum(r["l"] for r in results),
                "pts": sum(r["pts"] for r in results),
                "fpts": sum(r["fpts"] for r in results),
                "g": g,
                "a": a,
                "ga": g + a,
                "streak": best,
                "from": best_from,
                "to": best_to,
            }
        )
    managers.sort(key=lambda m: (-m["pts"], -m["fpts"]))

    def span(m):
        return f"тур {m['from']}" if m["from"] == m["to"] else f"туры {m['from']}–{m['to']}"

    tour_scores = [
        {"tour": p, "team": team_name[s["team_id"]], "fpts": s["fpts"]} for p in range(1, tour + 1) for s in standings[p]
    ]
    leader = managers[0]

    line(
        "- 🏅 **РЕКОРД лиги (лучший результат менеджера за тур):** "
        + "; ".join(f"**{x['team']}** — {fmt(x['fpts'])}, тур {x['tour']}" for x in top(tour_scores, lambda x: x["fpts"]))
    )
    line(
        "- 💀 **Антирекорд (худший результат менеджера за тур):** "
        + "; ".join(
            f"**{x['team']}** — {fmt(x['fpts'])}, тур {x['tour']}"
            for x in top(tour_scores, lambda x: x["fpts"], smallest=True)
        )
    )
    line("- 💰 **Сумма очков:** " + ", ".join(f"**{m['team']}** — {fmt(m['fpts'])}" for m in top(managers, lambda m: m["fpts"])))
    line(
        "- ⚽🅰 **Лучший по Г+П:** "
        + ", ".join(
            f"**{m['team']}** — {whole(m['ga'])} (голы {whole(m['g'])} + передачи {whole(m['a'])})"
            for m in top(managers, lambda m: m["ga"])
        )
    )
    line(
        f"- 👑 **Лидер фентези:** **{leader['team']}** — {whole(leader['pts'])} очк. в турнирной таблице "
        f"({whole(leader['w'])}-{whole(leader['d'])}-{whole(leader['l'])}), сумма очков {fmt(leader['fpts'])}"
    )
    line(
        "- 🔥 **Самый длинный стрик (без поражений):** "
        + ", ".join(f"**{m['team']}** — {m['streak']} ({span(m)})" for m in top(managers, lambda m: m["streak"]))
    )
    line()

    line("### Таблица менеджеров")
    line()
    table(
        ["#", "Менеджер", "В-Н-П", "Очки", "Сумма FPts", "Голы", "Пасы", "Г+П"],
        [
            [
                i,
                m["team"],
                f"{whole(m['w'])}-{whole(m['d'])}-{whole(m['l'])}",
                whole(m["pts"]),
                fmt(m["fpts"]),
                whole(m["g"]),
                whole(m["a"]),
                whole(m["ga"]),
            ]
            for i, m in enumerate(managers, start=1)
        ],
    )

    line("### 🌟 Сборная сезона (один лучший на позицию)")
    line()
    rows = []
    for pos in "GDMF":
        candidates = [x for x in players if x["pos"] == pos]
        if candidates:
            b = min(candidates, key=lambda x: (-x["fpts"], x["tour"], name_key(x)))
            rows.append([pos, fmt(b["fpts"]), b["name"], b["club"], owner_text(b), b["tour"]])
    table(["Поз.", "Очки", "Игрок", "Клуб", "У кого", "Тур"], rows)

    line("### 🔟 10 лучших выступлений игроков за сезон")
    line()
    best_players = sorted(players, key=by_points_desc(name_key))[:10]
    table(
        ["#", "Очки", "Игрок", "Тур"],
        [[i, fmt(x["fpts"]), x["name"], x["tour"]] for i, x in enumerate(best_players, start=1)],
    )

    line("### 🏆 Лучший перформанс менеджеров (лучший в каждом туре)")
    line()
    best_managers = []
    for p in range(1, tour + 1):
        for s in top(standings[p], lambda x: x["fpts"]):
            best_managers.append({"tour": p, "team": team_name[s["team_id"]], "fpts": s["fpts"]})
    best_managers.sort(key=lambda x: (-x["fpts"], x["tour"]))
    table(
        ["#", "Очки", "Менеджер", "Тур"],
        [[i, fmt(x["fpts"]), x["team"], x["tour"]] for i, x in enumerate(best_managers, start=1)],
    )

    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Отчёт по лиге Fantrax за тур и сезон")
    parser.add_argument("--tour", type=int, default=1, help="номер тура (сезон считается как туры 1..N)")
    parser.add_argument("--league-id", default="rwoc4s02mrui4mac")
    parser.add_argument("--out-file", help="сохранить отчёт в файл (UTF-8)")
    parser.add_argument("--docx", help="сохранить отчёт в файл .docx")
    parser.add_argument("--super-top", type=float, default=30, help="порог очков для супертопов")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    api = Fantrax(args.league_id)
    standings, team_name, team_ids, roster, players = load_data(api, args.tour)
    validate(standings, team_name, roster, args.tour)
    text = build_report(args.tour, standings, team_name, team_ids, roster, players, args.super_top)
    if args.out_file:
        with open(args.out_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    if args.docx:
        from md_to_docx import markdown_to_docx

        markdown_to_docx(text, args.docx)
    print(text)


if __name__ == "__main__":
    main()
