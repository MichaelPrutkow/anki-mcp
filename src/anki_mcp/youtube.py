import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi

from anki_mcp.server import WEB_READ, tool

MAX_TRANSCRIPT_CHARS = 8000
MAX_CACHED_VIDEOS = 8
OUTLINE_STEP_SECONDS = 90


@dataclass
class Video:
    segments: list[tuple[float, float, str]]  # (start, end, text)
    language: str
    translated: bool


class TimeInterval(BaseModel):
    start_sec: int = Field(description="Start time in seconds")
    end_sec: int = Field(description="End time in seconds")


_videos: dict[tuple[str, str], Video] = {}


def _timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def choose(transcripts: Iterable[Any], language: str | None) -> tuple[Any, bool]:
    """The transcript to read and whether it is machine-translated.

    Without a language: the video's own, the one YouTube generated from the speech, or a manual one in its
    language. With a language: a transcript in it, otherwise the first one translated into it.
    """
    available = list(transcripts)
    if not available:
        raise ToolError("This video has no transcripts.")
    if language:
        wanted = language.lower()
        for transcript in available:
            code = transcript.language_code.lower()
            if code == wanted or code.startswith(wanted + "-"):
                return transcript, False
        if not available[0].is_translatable:
            raise ToolError(f"The {available[0].language} transcript cannot be translated.")
        return available[0].translate(language), True
    generated = [t for t in available if t.is_generated]
    manual = [t for t in available if not t.is_generated]
    if generated:
        spoken = generated[0].language_code
        return next((t for t in manual if t.language_code == spoken), generated[0]), False
    return manual[0], False


def _fetch(url: str, language: str | None) -> Video:
    match = re.search(r"(?:v=|/)([0-9A-Za-z_-]{11})", url)
    if not match:
        raise ToolError(f"Invalid YouTube URL: {url}")
    try:
        transcripts = YouTubeTranscriptApi().list(match.group(1))
    except TranscriptsDisabled:
        raise ToolError("Transcripts are disabled for this video.") from None
    except NoTranscriptFound:
        raise ToolError("This video has no transcripts.") from None

    transcript, translated = choose(transcripts, language)
    snippets = transcript.fetch().snippets
    code = language if translated else transcript.language_code
    return Video([(s.start, s.start + s.duration, s.text.strip()) for s in snippets], code, translated)


def _outline(video: Video) -> str:
    lines, bucket = [], -1
    for i, (start, _, _) in enumerate(video.segments):
        if int(start // OUTLINE_STEP_SECONDS) == bucket:
            continue
        bucket = int(start // OUTLINE_STEP_SECONDS)
        words = " ".join(t for _, _, t in video.segments[i : i + 15]).split()[:25]
        lines.append(f"[{_timestamp(start)}] {' '.join(words)}")
    return "\n".join(lines)


@tool("YouTube transcript", WEB_READ)
async def youtube_transcript(
    url: str,
    intervals: Annotated[list[TimeInterval] | None, Field(max_length=30)] = None,
    language: Annotated[
        str | None,
        Field(min_length=2, description="Language code, e.g. 'de'. Without it: the video's own language"),
    ] = None,
) -> str:
    """Read the transcript of a YouTube video, in the video's own language unless another is asked for.

    A long video returns a timestamped outline instead; call again with 'intervals' to read the parts that matter.
    """
    key = (url, language or "")
    if key not in _videos:
        if len(_videos) >= MAX_CACHED_VIDEOS:
            _videos.pop(next(iter(_videos)))
        _videos[key] = await asyncio.to_thread(_fetch, url, language)
    video = _videos[key]
    note = f"\n\n(transcript in '{video.language}'{', machine-translated' if video.translated else ''})"

    if intervals:
        blocks = []
        for iv in intervals:
            text = " ".join(t for start, end, t in video.segments if start <= iv.end_sec and end >= iv.start_sec)
            if text:
                blocks.append(f"[{_timestamp(iv.start_sec)}-{_timestamp(iv.end_sec)}]\n{text}")
        return ("\n\n".join(blocks) or "No text in these intervals.") + note

    full = " ".join(t for _, _, t in video.segments)
    if len(full) <= MAX_TRANSCRIPT_CHARS:
        return full + note
    return "Transcript too long. Call again with 'intervals' picked from this outline:\n\n" + _outline(video) + note
