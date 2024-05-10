#! /usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import asyncio
import os
import sys

import dateparser
import feedparser
from loguru import logger
from videogram.utils import load_json, save_json
from videogram.videogram import sync
from videogram.ytdlp import ytdlp_extract_info


class YouTube:
    def __init__(self, database: dict) -> None:
        self.db = database

    def parse_entry_info(self, entry: dict) -> dict:
        res = {
            "banned": False,
            "not_finished": False,
        }
        info = ytdlp_extract_info(entry["link"], playlist=False)[0]
        if info.get("live_status") in {"is_upcoming", "is_live", "post_live"}:
            logger.warning(f"Skip not finished video: {entry['title']}")
            res["not_finished"] = True
            return res

        # skip banned video
        if info.get("availability") == "needs_auth":
            logger.warning(f"Skip banned video: {entry['title']}")
            res["banned"] = True
            return res

        logger.warning(f"Found a new video: {entry['title']}")
        return res

    async def process_single_entry(self, entry: dict) -> dict:
        res = {"updated": False}

        entry_info = self.parse_entry_info(entry)
        if entry_info["not_finished"]:
            return res

        if entry_info["banned"]:
            res["updated"] = True
            return res

        logger.info(f"Syncing to Telegram: {entry['title']}")
        await sync(entry["link"], tg_id=self.db["tg_target"], playlist=False)
        res["updated"] = True

        return res


async def main():
    # initialize youtube
    db: dict = load_json(args.database)
    youtube = YouTube(db)
    if "videos" not in db:
        db["videos"] = []

    # process unfinished feed
    for entry in db["videos"]:
        if entry["finished"]:
            continue
        logger.info(f"Process unfinished video: [{entry['link']}] {entry['title']}")
        res = await youtube.process_single_entry(entry)
        if res["updated"]:
            entry["finished"] = True
            save_json(db, args.database)

    # process new
    database_vids = {x["link"] for x in db["videos"]}
    remote = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={db['channel_id']}")
    for entry in remote["entries"][::-1]:  # from oldest to latest
        if entry["link"] in database_vids:
            logger.debug(f"Skip video in database: {entry['title']}")
            continue
        logger.info(f"New video found: [{entry['link']}] {entry['title']}")

        # Save the new entry first, mark it as not finished
        pub_time = dateparser.parse(entry["published"], settings={"TO_TIMEZONE": os.getenv("TZ", "UTC")})
        db["videos"].insert(0, {"title": entry["title"], "link": entry["link"], "time": f"{pub_time:%a, %d %b %Y %H:%M:%S %z}", "finished": False})
        save_json(db, args.database)

        res = await youtube.process_single_entry(entry)
        if res["updated"]:
            db["videos"][0]["finished"] = True
            save_json(db, args.database)


if __name__ == "__main__":
    # parse arguments
    parser = argparse.ArgumentParser(description="Sync YouTube to Telegram")
    parser.add_argument("--database", type=str, default="data/youtube.json", required=False, help="Path to database.")
    args = parser.parse_args()

    # loguru settings
    logger.remove()  # Remove default handler.
    logger.add(
        sys.stderr,
        colorize=True,
        level=os.getenv("LOG_LEVEL", "DEBUG"),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green>| <level>{level: <7}</level> | <cyan>{name: <10}</cyan>:<cyan>{function: ^30}</cyan>:<cyan>{line: >4}</cyan> - <level>{message}</level>",
    )
    asyncio.run(main())
