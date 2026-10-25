"""Готовит данные для бота: data/tour_N.md (отчёт тура) и data/season.md (сезон по последний тур).

Примеры:
    python update_data.py --tour 7          # обновить только тур 7 и сезон
    python update_data.py --all 7           # пересобрать туры 1..7 (долго)
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SEASON_MARK = "#статистикасезона"


def build(tour):
    path = os.path.join(DATA, f"tour_{tour}.md")
    subprocess.run(
        [sys.executable, os.path.join(HERE, "fantrax_report.py"), "--tour", str(tour), "--out-file", path],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return path


def save_season(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    season = text[text.index(SEASON_MARK) :]
    with open(os.path.join(DATA, "season.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(season)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tour", type=int, help="обновить этот тур и сезон")
    group.add_argument("--all", type=int, help="пересобрать туры 1..N")
    args = parser.parse_args()

    os.makedirs(DATA, exist_ok=True)
    tours = range(1, args.all + 1) if args.all else [args.tour]
    path = None
    for t in tours:
        print(f"Тур {t}...", file=sys.stderr)
        path = build(t)
    save_season(path)
    print("Готово", file=sys.stderr)


if __name__ == "__main__":
    main()
