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

from models import TranscriptResult, VideoMetadata

YT_DLP_OPTS: Final[dict[str, Any]] = {
    "quiet": True,
    "extract_flat": "in_playlist",
    "skip_download": True,
}


def build_playlist_ytdlp_url(identifier: str) -> str:
    """Convert a valid ID into a playlist URL.

    Args:
        identifier: The raw YouTube playlist ID.

    Returns:
        The full YouTube playlist URL.
    """
    clean_id: str = identifier.strip()
    return f"https://www.youtube.com/playlist?list={clean_id}"


def build_channel_ytdlp_url(handle: str) -> str:
    """Convert a valid handle into a channel URL.

    Args:
        handle: The creator's handle, with or without the '@' prefix.

    Returns:
        The full YouTube channel videos URL.
    """
    clean_handle: str = handle.strip()
    if not clean_handle.startswith("@"):
        clean_handle = f"@{clean_handle}"
    return f"https://www.youtube.com/{clean_handle}/videos"


def fetch_records(url: str) -> list[VideoMetadata]:
    """Scrape video metadata from either a playlist or channel URL.

    Args:
        url: The full YouTube playlist or channel URL to scrape.

    Returns:
        A list of parsed VideoMetadata tuples.
    """
    records: list[VideoMetadata] = []

    try:
        with yt_dlp.YoutubeDL(YT_DLP_OPTS) as ydl:
            info: dict[str, Any] | None = ydl.extract_info(
                url,
                download=False,
            )
    except yt_dlp.utils.DownloadError:
        return records

    if info is None:
        return records

    try:
        entries: list[dict[str, Any]] = info["entries"]
    except KeyError:
        return records

    for entry in entries:
        parsed: VideoMetadata | None = _get_record(entry)
        if parsed is not None:
            records.append(parsed)

    return records


def _get_record(entry: Any) -> VideoMetadata | None:
    """Extract a VideoMetadata tuple from a raw yt-dlp entry dictionary.

    Args:
        entry: A raw dictionary representing a video entry from yt-dlp.

    Returns:
        A VideoMetadata tuple, or None if the entry is missing a video ID
        or is malformed.
    """
    try:
        video_id: str | None = entry.get("id")
    except AttributeError:
        # Fails immediately if entry is None or not a dict-like object
        return None

    if video_id is None:
        return None

    formatted_date: datetime.date | None = None
    try:
        raw_date: str = entry["upload_date"]
        formatted_date = datetime.date(
            int(raw_date[:4]),
            int(raw_date[4:6]),
            int(raw_date[6:8]),
        )
    except KeyError, TypeError, ValueError, IndexError:
        formatted_date = None

    duration: int | None = None
    try:
        duration = int(entry["duration"])
    except KeyError, TypeError, ValueError:
        duration = None

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
    """Fetch transcripts for a batch of video IDs concurrently using threads.

    Args:
        video_ids: List of YouTube video IDs to transcribe.
        max_retries_per_video: Maximum retry attempts per video on failure.
        max_workers: Size of the thread pool executor.

    Returns:
        A list of TranscriptResult tuples containing fetch statuses.
    """
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
    """Fetch one transcript with exponentially increasing delays for rate limits.

    Args:
        video_id: The target YouTube video ID.
        ytt_api: An instance of YouTubeTranscriptApi.
        max_retries: Number of retry attempts before returning a failure status.

    Returns:
        A TranscriptResult indicating success, permanent failure, or retryable error.
    """
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
            return TranscriptResult(
                video_id=video_id,
                transcript=None,
                status="NO TRANSCRIPT",
                error=str(e),
            )

        except VideoUnavailable as e:
            return TranscriptResult(
                video_id=video_id,
                transcript=None,
                status="UNAVAILABLE",
                error=str(e),
            )

        except Exception as e:
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


def extract_transcript(
    transcript_result: TranscriptResult,
) -> FetchedTranscript | None:
    """Extract the FetchedTranscript from a TranscriptResult.

    Args:
        transcript_result: The result object returned by the transcript fetcher.

    Returns:
        The underlying FetchedTranscript object, or None if it is missing.
    """
    try:
        return transcript_result.transcript
    except AttributeError:
        return None
