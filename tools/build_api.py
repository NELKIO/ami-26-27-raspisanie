"""Собирает JSON-API расписания ПМИ: api/v1/pmi/index.json и api/v1/pmi/<группа>.json.

Run: python3 -I tools/build_api.py [--out api/v1/pmi]
Requires: pip install playwright && playwright install chromium

Страница открывается в headless-браузере с локального http-сервера, сама грузит книгу из Google
и разбирает её своим кодом; скрипт только забирает window.RaspisAPI.build(). Если живая загрузка
не удалась (кэш/встроенный снимок), файлы не трогаются и скрипт падает — в API не попадут
устаревшие данные.
"""
import argparse
import functools
import json
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def launch(p):
    try:
        return p.chromium.launch(channel="chrome")
    except Exception:
        return p.chromium.launch()


def build():
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = launch(p)
            page = browser.new_page(timezone_id="Europe/Moscow", locale="ru-RU")
            page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
            # update() ставит «loading» синхронно при загрузке страницы, дальше — live/cache/snapshot
            page.wait_for_function("window.RaspisAPI && RaspisAPI.state() !== 'loading'", timeout=120_000)
            state = page.evaluate("RaspisAPI.state()")
            if state != "live":
                raise SystemExit(f"живая загрузка не удалась (state={state}) — API не обновляю")
            data = page.evaluate("RaspisAPI.build()")
            browser.close()
    finally:
        server.shutdown()
    return data


def check(data):
    index, groups = data["index"], data["groups"]
    if len(groups) < 20:
        raise SystemExit(f"подозрительно мало групп: {len(groups)}")
    for g in index["pinned"]:
        if not any(day["pairs"] for day in groups[g]["days"]):
            raise SystemExit(f"у закреплённой группы {g} нет ни одной пары — не публикую")


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def write(data, out):
    out.mkdir(parents=True, exist_ok=True)
    keep = {"index.json"}
    (out / "index.json").write_text(dump(data["index"]), encoding="utf-8")
    for name, group in data["groups"].items():
        fn = f"{name}.json"
        keep.add(fn)
        (out / fn).write_text(dump(group), encoding="utf-8")
    for old in out.glob("*.json"):
        if old.name not in keep:
            old.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "api" / "v1" / "pmi"))
    args = ap.parse_args()
    data = build()
    check(data)
    write(data, Path(args.out))
    total = sum(len(d["pairs"]) for g in data["groups"].values() for d in g["days"])
    print(f"ok: {len(data['groups'])} групп, {data['index']['range']}, пар по датам: {total}", file=sys.stderr)


if __name__ == "__main__":
    main()
