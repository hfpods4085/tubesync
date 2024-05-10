#! /usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import os
import sys
from pathlib import Path

import dateparser
import feedparser
from loguru import logger
from videogram.utils import load_json, save_json


def main():
    feeds = feedparser.parse(f"{os.getenv('RSSHUB_URL', 'https://rsshub.app')}/bilibili/user/video-all/{args.uid}")

    # fetch all remote videos
    videos = []
    for entry in feeds["entries"]:
        pub_time = dateparser.parse(entry["published"], settings={"TO_TIMEZONE": os.getenv("TZ", "UTC")})
        logger.info(f"Found: [{pub_time:%Y-%m-%d %H:%M:%S}] {entry['title']}")
        videos.append({"title": entry["title"], "link": entry["link"], "time": f"{pub_time:%a, %d %b %Y %H:%M:%S %z}", "finished": False})

    # mark finished videos
    db = load_json(args.database) if args.database else {}
    db_videos = db.get("videos", [])
    db_links = [x["link"] for x in db_videos]
    for video in videos:
        if video["link"] in db_links:
            db_video = next(x for x in db_videos if x["link"] == video["link"])
            video["finished"] = db_video["finished"]

    # save to database
    db_path = args.database if args.database else f"data/bilibili-{args.channel_id}.json"
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db["channel_id"] = args.channel_id
    db["tg_target"] = db.get("tg_target", None)
    db["videos"] = videos
    logger.info(f"Saving {len(videos)} to: {db_path}")
    save_json(db, db_path)


if __name__ == "__main__":
    # parse arguments
    parser = argparse.ArgumentParser(description="Fetch all video ids of Bilibili")
    parser.add_argument("-c", "--channel-id", type=int, required=True, help="Bilibili user id.")
    parser.add_argument("-d", "--database", type=str, required=False, help="Existing database of this user.")
    args = parser.parse_args()

    # loguru settings
    logger.remove()  # Remove default handler.
    logger.add(
        sys.stderr,
        colorize=True,
        level=os.getenv("LOG_LEVEL", "DEBUG"),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green>| <level>{level: <7}</level> | <cyan>{name: <10}</cyan>:<cyan>{function: ^30}</cyan>:<cyan>{line: >4}</cyan> - <level>{message}</level>",
    )
    main()
