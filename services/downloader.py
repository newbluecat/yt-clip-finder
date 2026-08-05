import concurrent.futures
import datetime
import random
import time
from typing import Any, Final

import yt_dlp
from youtube_transcript_api import (
    FetchedTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

from models import TranscriptResult, VideoMetadata, TranscriptChunk

YT_DLP_OPTS: Final[dict[str, Any]] = {
    "quiet": True,
    "extract_flat": "in_playlist",
    "skip_download": True,
}
UPLOAD_DATE_LENGTH: Final[int] = 8


def build_playlist_ytdlp_url(identifier: str) -> str:
    """Convert a valid ID into a playlist url."""
    clean_id: str = identifier.strip()
    return f"https://www.youtube.com/playlist?list={clean_id}"


def build_channel_ytdlp_url(handle: str) -> str:
    """Convert a valid ID into a channel url."""
    clean_handle: str = handle.strip()
    if not clean_handle.startswith("@"):
        clean_handle = f"@{clean_handle}"
    return f"https://www.youtube.com/@{clean_handle}/videos"


def fetch_records(url: str) -> list[VideoMetadata]:
    """Scrapes video metadata from either a playlist or channel URL."""
    records: list[VideoMetadata] = []

    try:
        with yt_dlp.YoutubeDL(YT_DLP_OPTS) as ydl:
            info: dict[str, Any] | None = ydl.extract_info(
                url,
                download=False,
            )
    except yt_dlp.utils.DownloadError:
        return records

    if not info:
        return records

    entries: list[dict[str, Any]] = info.get("entries", [])
    for entry in entries:
        parsed: VideoMetadata | None = _get_record(entry)
        if parsed:
            records.append(parsed)

    return records


def _get_record(entry: dict[str, Any] | None) -> VideoMetadata | None:
    """Extract a VideoMetadata tuple from an entry from a yt-dlp dictionary."""
    if entry is None or not isinstance(entry, dict):
        return None

    video_id: str | None = entry.get("id")
    if video_id is None:
        return None

    raw_date: str | None = entry.get("upload_date")
    formatted_date: datetime.date | None = None
    if raw_date and len(raw_date) == UPLOAD_DATE_LENGTH and raw_date.isdigit():
        formatted_date = datetime.date(
            int(raw_date[:4]),
            int(raw_date[4:6]),
            int(raw_date[6:8]),
        )

    raw_duration: float | int | None = entry.get("duration")
    duration: int | None = int(raw_duration) if raw_duration is not None else None

    return VideoMetadata(
        video_id=video_id,
        title=entry.get("title"),
        channel=entry.get("channel") or entry.get("uploader"),
        channel_id=entry.get("channel_id") or entry.get("uploader_id"),
        upload_date=formatted_date,
        duration_seconds=duration,
    )


def fetch_transcripts(
    video_ids: list[str],
    max_retries_per_video: int = 3,
    max_workers: int = 3,
) -> list[TranscriptResult]:
    """Fetch transcripts for a batch of video IDs concurrently using threads."""
    ytt_api: YouTubeTranscriptApi = YouTubeTranscriptApi()
    results: list[TranscriptResult] = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers,
    ) as executor:
        futures: list[concurrent.futures.Future[TranscriptResult]] = [
            executor.submit(
                _get_transcript,
                video_id=video_id,
                ytt_api=ytt_api,
                max_retries=max_retries_per_video,
            )
            for video_id in video_ids
        ]

        for future in concurrent.futures.as_completed(futures):
            result: TranscriptResult | None = future.result()
            if result is not None:
                results.append(result)

    return results


def _get_transcript(
    video_id: str,
    ytt_api: YouTubeTranscriptApi,
    max_retries: int = 3,
) -> TranscriptResult:
    """Fetch one transcript with exponentially increasing delays for rate limits."""
    for attempt in range(max_retries):
        try:
            time.sleep(random.uniform(0.3, 0.8))

            transcript: FetchedTranscript = ytt_api.fetch(video_id)
            return TranscriptResult(
                video_id=video_id,
                transcript=transcript,
                status="SUCCESS",
                error=None,
            )

        except (TranscriptsDisabled, NoTranscriptFound) as e:
            # video has no transcripts or transcript disabled
            return TranscriptResult(
                video_id=video_id,
                transcript=None,
                status="NO TRANSCRIPT",
                error=str(e),
            )

        except VideoUnavailable as e:
            # video not found
            return TranscriptResult(
                video_id=video_id,
                transcript=None,
                status="UNAVAILABLE",
                error=str(e),
            )

        except Exception as e:
            # probably 429 rate limit
            if attempt == max_retries - 1:
                return TranscriptResult(
                    video_id=video_id,
                    transcript=None,
                    status="RETRYABLE",
                    error=f"ERROR: Failed after {max_retries} attempt(s): {e}",
                )

            sleep_time: float = (2**attempt) + random.uniform(0.5, 1.5)
            time.sleep(sleep_time)

    return TranscriptResult(
        video_id=video_id,
        transcript=None,
        status="RETRYABLE",
        error="Aborted without execution",
    )

def extract_transcript(transcript_result: TranscriptResult) -> FetchedTranscript:
    """Extract the FetchedTranscript from TranscriptResult.
    """


def chunk_transcript() -> list[TranscriptChunk]:

