#! /usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dateparser
import requests
from loguru import logger
from videogram.utils import load_json, save_json
from videogram.ytdlp import ytdlp_extract_info
from yt_dlp.utils import YoutubeDLError


def get_pubdate_via_api(urls: list[str]) -> list[datetime]:
    vids = [Path(url).stem.removeprefix("watch?v=") for url in urls]
    pub_times = []
    max_per_query = 50  # YouTube API limit
    if len(vids) <= max_per_query:
        api_url_list = [f"https://youtube.googleapis.com/youtube/v3/videos?part=snippet&id={'%2C'.join(vids)}&key={os.environ['YOUTUBE_API_KEY']}"]
    else:
        vid_lists = [vids[i : i + max_per_query] for i in range(0, len(vids), max_per_query)]
        api_url_list = [f"https://youtube.googleapis.com/youtube/v3/videos?part=snippet&id={'%2C'.join(x)}&key={os.environ['YOUTUBE_API_KEY']}" for x in vid_lists]
    for api_url in api_url_list:
        resp = requests.get(api_url, timeout=5).json()
        pub_times.extend([x["snippet"]["publishedAt"] for x in resp["items"]])
    return [dateparser.parse(pub_time, settings={"TIMEZONE": "UTC", "TO_TIMEZONE": os.getenv("TZ", "UTC")}) for pub_time in pub_times]  # type: ignore


def add_pubdate_for_videos(videos: list[dict]):
    # method 1, via YOUTUBE_API_KEY, fast
    # method 2, via yt-dlp parse one by one , very slow
    if os.getenv("YOUTUBE_API_KEY"):
        logger.info("Querying video publish time via YouTube API")
        pub_times = get_pubdate_via_api([x["link"] for x in videos])
        videos = [{**x, "time": f"{pub_time:%a, %d %b %Y %H:%M:%S %z}"} for x, pub_time in zip(videos, pub_times, strict=True)]
        videos = [{**x, "timestamp": pub_time.timestamp()} for x, pub_time in zip(videos, pub_times, strict=True)]  # add timestamp for sorting
    else:
        logger.warning("Querying video publish time via yt-dlp, very slow!")
        for video in videos:
            detail_info = ytdlp_extract_info(video["link"])[0]
            if isinstance(detail_info.get("release_timestamp"), int):
                timestamp = detail_info["release_timestamp"]
                video["time"] = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).strftime("%a, %d %b %Y %H:%M:%S %z")
                video["timestamp"] = timestamp
            else:
                video["time"] = detail_info["upload_date"]
                video["timestamp"] = detail_info["upload_date"]
            if detail_info.get("availability") == "needs_auth":
                logger.warning(f"Mark banned video as finished: {video['title']}")
                video["finished"] = True

    sorted_videos = sorted(videos, key=lambda x: x["timestamp"], reverse=True)
    # delete timestamp key
    for video in sorted_videos:
        del video["timestamp"]
    return sorted_videos


def get_palylist_entries(url: str):
    info: list[dict] = ytdlp_extract_info(url, playlist=False)
    entries = []
    for entry in info[0]["entries"]:
        if not entry.get("view_count"):
            logger.warning(f"Skip not available video [{entry['id']}]: {entry['title']}")
            continue
        entries.append(entry)
    logger.info(f"Found {len(entries)} entries for playlist: {info[0]['title']}")
    return entries


def main():
    # fetch "videos", "live" and "shorts" section of this channel
    info: list[dict] = ytdlp_extract_info(f"https://www.youtube.com/channel/{args.channel_id}", playlist=False)
    total_entries = []
    for entry in info[0]["entries"]:
        # if this channel has "videos", "live", "shorts" section, entry is still a playlist. Otherwise, it's a video.
        if "entries" not in entry:
            total_entries.append(entry)
            continue
        entries = list(entry["entries"])
        logger.info(f"Found {len(entries)} entries in {entry['title']}")
        total_entries.extend(entries)
    logger.info(f"Total: {len(total_entries)} entries of {entry['channel']}")

    # fetch "playlist" section of this channel
    saved_urls = [x["url"] for x in total_entries]
    try:
        info: list[dict] = ytdlp_extract_info(f"https://www.youtube.com/channel/{args.channel_id}/playlists", playlist=False)
        for entry in info[0]["entries"]:
            palylist_entries = get_palylist_entries(entry["url"])
            total_entries.extend([x for x in palylist_entries if x["url"] not in saved_urls])
    except YoutubeDLError as e:
        if e.msg.endswith("This channel does not have a playlists tab"):  # type: ignore
            logger.warning("This channel does not have playlists, skiping ...")

    # get all videos
    videos = []
    for entry in total_entries:
        logger.info(f"Found a new video [{entry['id']}]: {entry['title']}")
        if not args.save_shorts and "/shorts/" in entry["url"]:
            logger.warning(f"Skip YouTube shorts: {entry['title']}")
            continue
        video_info = {"title": entry["title"], "link": entry["url"], "finished": False}
        videos.append(video_info)

    # query publish time.
    if args.query_pubdate:
        videos = add_pubdate_for_videos(videos)

    # mark finished videos
    db = load_json(args.database) if args.database else {}
    db_videos = db.get("videos", [])
    db_links = [x["link"] for x in db_videos]
    for video in videos:
        if video["link"] in db_links and not video["finished"]:
            db_video = next(x for x in db_videos if x["link"] == video["link"])
            video["finished"] = db_video["finished"]

    # save to database
    db_path = args.database if args.database else f"data/youtube-{args.channel_id}.json"
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db["channel_id"] = args.channel_id
    db["tg_target"] = db.get("tg_target", None)
    db["videos"] = videos
    logger.info(f"Saving {len(videos)} to: {db_path}")
    save_json(db, db_path)


if __name__ == "__main__":
    # parse arguments
    parser = argparse.ArgumentParser(description="Fetch all video ids of YouTube")
    parser.add_argument("-c", "--channel-id", type=str, required=True, help="YouTube channel id.")
    parser.add_argument("-d", "--database", type=str, required=False, help="Existing database of this channel.")
    parser.add_argument("--save-shorts", action="store_true", help="Whether to save YouTube shorts.")
    parser.add_argument("--query-pubdate", action="store_true", help="Query video publish time. Very slow! (Set YOUTUBE_API_KEY to speedup)")
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
