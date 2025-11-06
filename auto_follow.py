#!/usr/bin/env python3
"""
Download the newest uploads from one or more YouTube channels with yt-dlp.

Usage example:
    python auto_follow.py --config channels.json --download-dir downloads
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from shutil import which
from typing import Any, Dict, Iterable, List, Optional

try:
    import yt_dlp
    from yt_dlp.utils import DateRange
except ImportError:  # pragma: no cover - import guard for better error message
    print(
        "Missing dependency: yt-dlp. Install it with 'pip install yt-dlp' before running.",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency
    requests = None

DEFAULT_CONFIG = "channels.json"
DEFAULT_DOWNLOAD_DIR = "downloads"
DEFAULT_ARCHIVE_DIR = ".archives"
DEFAULT_FORMAT = "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/bv*[height<=1080]+ba/b[ext=mp4]/b"
KEEP_MERGE_TOKEN = "keep"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download new uploads from YouTube channels listed in a config file.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"Path to JSON config listing channels (default: {DEFAULT_CONFIG}).",
    )
    parser.add_argument(
        "--download-dir",
        default=DEFAULT_DOWNLOAD_DIR,
        help=f"Folder that will receive the videos (default: {DEFAULT_DOWNLOAD_DIR}).",
    )
    parser.add_argument(
        "--archive-dir",
        default=DEFAULT_ARCHIVE_DIR,
        help=(
            "Folder holding download history files per channel. "
            "Keep between runs to avoid duplicate downloads (default: .archives)."
        ),
    )
    parser.add_argument(
        "--format",
        default=DEFAULT_FORMAT,
        help=(
            "yt-dlp format selector. Default prefers 1080p MP4 + M4A and falls back sensibly."
        ),
    )
    parser.add_argument(
        "--max-downloads",
        type=int,
        default=0,
        help=(
            "Limit number of videos fetched per channel per run. "
            "0 means no limit (default)."
        ),
    )
    parser.add_argument(
        "--since",
        help=(
            "Only download videos uploaded on/after this date. "
            "Accepts YYYY-MM-DD, 'yesterday', or 'today'."
        ),
    )
    parser.add_argument(
        "--merge-format",
        default="mp4",
        help=(
            "Container to remux into when video/audio need merging (default: mp4). "
            f"Use '{KEEP_MERGE_TOKEN}' to keep original container."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List items without downloading them.",
    )
    return parser.parse_args(argv)


def load_channels(config_path: Path) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file '{config_path}' not found. "
            "Create it with a 'channels' list, e.g. "
            '{"channels": [{"url": "https://www.youtube.com/@Example"}]}.'
        )
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    channels = data.get("channels")
    if not channels:
        raise ValueError("Config file must contain a non-empty 'channels' list.")
    for index, entry in enumerate(channels):
        if "url" not in entry:
            raise ValueError(f"Channel entry #{index} missing required 'url' field: {entry}")
    return channels, data


def slugify(value: str) -> str:
    """Convert an arbitrary label into a safe folder/file name."""
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized or "channel"


def infer_label(channel: Dict[str, Any]) -> str:
    if "label" in channel and channel["label"]:
        return str(channel["label"])
    url = str(channel["url"])
    for segment in reversed(url.rstrip("/").split("/")):
        if segment:
            return segment
    return url


def normalize_since(value: str) -> str:
    """Convert friendly date input into yt-dlp's YYYYMMDD format."""
    slug = value.strip().lower()
    today = date.today()
    if slug == "today":
        target = today
    elif slug == "yesterday":
        target = today - timedelta(days=1)
    else:
        try:
            target = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(
                f"Cannot parse date '{value}'. Use YYYY-MM-DD, 'today', or 'yesterday'."
            ) from exc
    return target.strftime("%Y%m%d")


def download_channel(
    channel: Dict[str, Any],
    download_dir: Path,
    archive_dir: Path,
    *,
    video_format: str,
    max_downloads: int,
    min_date: str | None,
    merge_format: str,
    dry_run: bool,
) -> Dict[str, Any]:
    label = infer_label(channel)
    safe_label = slugify(label)
    channel_dir = download_dir / safe_label
    archive_path = archive_dir / f"{safe_label}.txt"
    channel_dir.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    before_ids = load_archive_ids(archive_path)

    downloaded_items: List[Dict[str, str]] = []
    progress_hook = build_progress_hook(downloaded_items)

    ydl_opts: Dict[str, Any] = {
        "ignoreerrors": True,
        "quiet": False,
        "format": video_format,
        "paths": {"home": str(channel_dir)},
        "outtmpl": "%(upload_date)s - %(title)s [%(id)s].%(ext)s",
        "clean_infojson": True,
        "download_archive": str(archive_path),
        "noprogress": False,
        "progress_hooks": [progress_hook],
    }
    if max_downloads:
        ydl_opts["max_downloads"] = max_downloads
    if min_date:
        ydl_opts["daterange"] = DateRange(min_date, None)
    if merge_format and merge_format.lower() != KEEP_MERGE_TOKEN:
        ydl_opts["merge_output_format"] = merge_format
    if dry_run:
        ydl_opts["simulate"] = True

    url = str(channel["url"])
    print(f"\n=== Fetching updates for: {label} ({url}) ===")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    after_ids = load_archive_ids(archive_path)
    new_ids = after_ids - before_ids

    new_items = [
        item for item in downloaded_items if item.get("id") in new_ids
    ]

    # Fallback for ids not captured by hooks (rare).
    missing_ids = [vid_id for vid_id in new_ids if vid_id not in {item.get("id") for item in new_items}]
    for vid_id in missing_ids:
        new_items.append(
            {
                "id": vid_id,
                "title": "",
                "url": f"https://www.youtube.com/watch?v={vid_id}",
            }
        )

    return {"label": label, "items": new_items}

def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = Path(args.config).expanduser()
    download_dir = Path(args.download_dir).expanduser()
    archive_dir = Path(args.archive_dir).expanduser()
    video_format = args.format or DEFAULT_FORMAT

    try:
        channels, config_root = load_channels(config_path)
    except (FileNotFoundError, ValueError) as error:
        print(f"Config error: {error}", file=sys.stderr)
        return 1

    global_since = None
    if args.since:
        try:
            global_since = normalize_since(args.since)
        except ValueError as error:
            print(f"Date error: {error}", file=sys.stderr)
            return 1

    merge_format = args.merge_format or "mp4"
    if merge_format.lower() != KEEP_MERGE_TOKEN and not _has_merging_tool():
        print(
            "Warning: ffmpeg hoặc avconv không tìm thấy. "
            "yt-dlp sẽ không thể ghép audio/video thành một file duy nhất.\n"
            "Cài đặt ffmpeg (ví dụ: 'brew install ffmpeg') hoặc chạy lại với '--merge-format keep'.",
            file=sys.stderr,
        )

    if not channels:
        print("Nothing to do: channel list is empty.", file=sys.stderr)
        return 1

    # Ensure main folders exist before downloads start.
    download_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    messenger_notifier = _create_messenger_notifier(config_root.get("notifications", {}))

    failures = []
    results: List[Dict[str, Any]] = []
    for channel in channels:
        try:
            result = download_channel(
                channel,
                download_dir,
                archive_dir,
                video_format=video_format,
                max_downloads=args.max_downloads,
                min_date=_channel_since(channel, global_since),
                merge_format=merge_format,
                dry_run=args.dry_run,
            )
            results.append(result)
        except Exception as exc:  # pragma: no cover - resilient orchestration
            label = infer_label(channel)
            print(f"Failed to process {label}: {exc}", file=sys.stderr)
            failures.append(label)

    if failures:
        print(f"\nCompleted with {len(failures)} failures: {', '.join(failures)}.", file=sys.stderr)
        return 1

    if messenger_notifier and not args.dry_run:
        messenger_notifier.notify(results)

    print("\nAll channels processed successfully.")
    return 0


def _channel_since(channel: Dict[str, Any], fallback: str | None) -> str | None:
    raw = channel.get("since")
    if raw:
        return normalize_since(str(raw))
    return fallback


def load_archive_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            cleaned = line.strip()
            if not cleaned:
                continue
            parts = cleaned.split()
            ids.add(parts[-1])
    return ids


def build_progress_hook(collection: List[Dict[str, str]]):
    seen: set[str] = set()

    def hook(status: Dict[str, Any]) -> None:
        if status.get("status") != "finished":
            return
        info = status.get("info_dict") or {}
        vid_id = info.get("id")
        if not vid_id or vid_id in seen:
            return
        seen.add(vid_id)
        title = info.get("title") or ""
        url = (
            info.get("webpage_url")
            or info.get("original_url")
            or info.get("url")
            or f"https://www.youtube.com/watch?v={vid_id}"
        )
        collection.append(
            {
                "id": vid_id,
                "title": title,
                "url": url,
            }
        )

    return hook


def _create_messenger_notifier(config: Dict[str, Any]) -> Optional["MessengerNotifier"]:
    data = config.get("messenger")
    if not data:
        return None
    if requests is None:
        print(
            "Messenger notification requested but 'requests' library is missing. "
            "Install it with 'pip install requests'.",
            file=sys.stderr,
        )
        return None
    access_token = data.get("access_token")
    recipient_id = data.get("recipient_id")
    template = data.get("template")
    if not access_token or not recipient_id:
        print(
            "Messenger notification config requires 'access_token' and 'recipient_id'.",
            file=sys.stderr,
        )
        return None
    return MessengerNotifier(access_token, recipient_id, template)


class MessengerNotifier:
    GRAPH_ENDPOINT = "https://graph.facebook.com/v18.0/me/messages"

    def __init__(self, access_token: str, recipient_id: str, template: Optional[str] = None) -> None:
        self.access_token = access_token
        self.recipient_id = recipient_id
        self.template = template or (
            "Kênh {label} vừa tải {count} video mới:\n{items}"
        )

    def notify(self, results: List[Dict[str, Any]]) -> None:
        for result in results:
            items = result.get("items") or []
            if not items:
                continue
            message = self._render_message(result["label"], items)
            self._send_message(message)

    def _render_message(self, label: str, items: List[Dict[str, str]]) -> str:
        lines = []
        for item in items:
            title = item.get("title") or "(Không rõ tiêu đề)"
            url = item.get("url") or f"https://www.youtube.com/watch?v={item.get('id')}"
            lines.append(f"- {title}\n  {url}")
        body = "\n".join(lines)
        return self.template.format(label=label, count=len(items), items=body)

    def _send_message(self, message: str) -> None:
        payload = {
            "messaging_type": "UPDATE",
            "recipient": {"id": self.recipient_id},
            "message": {"text": message},
        }
        params = {"access_token": self.access_token}
        try:
            response = requests.post(self.GRAPH_ENDPOINT, params=params, json=payload, timeout=10)
            if response.status_code >= 400:
                print(
                    f"Messenger notification failed ({response.status_code}): {response.text}",
                    file=sys.stderr,
                )
        except Exception as exc:  # pragma: no cover - best-effort notification
            print(f"Messenger notification error: {exc}", file=sys.stderr)


def _has_merging_tool() -> bool:
    return which("ffmpeg") is not None or which("avconv") is not None


if __name__ == "__main__":
    raise SystemExit(main())
