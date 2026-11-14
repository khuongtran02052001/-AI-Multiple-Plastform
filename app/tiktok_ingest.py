"""Constrained TikTok-link ingestion for content owned or licensed by the operator.

This uses yt-dlp as a best-effort extractor, NOT a TikTok public download API.
The external platform may change its formats, block access or forbid download.
Avoid cookies, login bypass, watermark removal and any arbitrary URL fetching.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.db import new_id


class DownloadError(Exception):
    pass


_HOSTS = {'tiktok.com', 'www.tiktok.com', 'm.tiktok.com',
          'vm.tiktok.com', 'vt.tiktok.com'}
_LONG_VIDEO = re.compile(r'^/@[\w.\-]+/video/\d+/?$', re.ASCII)
_SHORT = re.compile(r'^/[A-Za-z0-9]+/?$')
_SHARE = re.compile(r'^/t/[A-Za-z0-9]+/?$')


def validate_tiktok_url(url: str) -> str:
    """Strictly accept ordinary HTTPS TikTok video URLs; no alternate hosts."""
    if not isinstance(url, str) or len(url) > 1000 or any(ch.isspace() for ch in url):
        raise DownloadError('Liên kết TikTok không hợp lệ.')
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or '').lower()
        port = parsed.port
    except ValueError as exc:
        raise DownloadError('Liên kết TikTok không hợp lệ.') from exc
    if (parsed.scheme != 'https' or hostname not in _HOSTS
            or parsed.username is not None or parsed.password is not None
            or port not in (None, 443)):
        raise DownloadError('Chỉ nhận liên kết HTTPS từ domain TikTok chính thức.')
    path = parsed.path
    if hostname in ('vm.tiktok.com', 'vt.tiktok.com'):
        valid = bool(_SHORT.fullmatch(path))
    else:
        valid = bool(_LONG_VIDEO.fullmatch(path) or _SHARE.fullmatch(path))
    if not valid:
        raise DownloadError('Cần URL trực tiếp tới một video TikTok, không nhận playlist hoặc hồ sơ.')
    # Remove tracking query params and fragments. A video ID or TikTok short code is sufficient.
    return urlunsplit(('https', hostname, path, '', ''))


def _probe(path: Path):
    try:
        completed = subprocess.run(
            ['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
             '-show_entries', 'format=duration:stream=codec_type,width,height',
             '-of', 'json', str(path)],
            check=True, capture_output=True, timeout=25)
        info = json.loads(completed.stdout)
        video = next(s for s in info.get('streams', []) if s.get('codec_type') == 'video')
        duration = float(info['format']['duration'])
        width, height = int(video['width']), int(video['height'])
        if duration <= 0 or width <= 0 or height <= 0:
            raise ValueError('Missing video metadata')
        if duration > 900:
            raise DownloadError(f'Video dài {int(duration)}s vượt quá giới hạn cho phép (tối đa 15 phút).')
        return duration, width, height
    except DownloadError:
        raise
    except (OSError, ValueError, KeyError, StopIteration,
            subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise DownloadError('File TikTok không phải MP4 có video hợp lệ.') from exc


def convert_to_vertical_short(file_info: dict) -> dict:
    """Convert landscape video (width > height) to vertical 9:16 (720x1280) with blurred background."""
    input_path = Path(file_info['path'])
    output_path = input_path.with_name(f"{file_info['id']}_short.mp4")

    filter_complex = (
        "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=15:1[bg];"
        "[0:v]scale=720:1280:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )
    cmd = [
        'ffmpeg', '-v', 'error', '-y',
        '-i', str(input_path),
        '-filter_complex', filter_complex,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        str(output_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=300)
        if res.returncode != 0 or not output_path.is_file():
            err = res.stderr.decode('utf-8', errors='ignore')[:200]
            output_path.unlink(missing_ok=True)
            raise DownloadError(f"Không thể chuyển đổi video sang định dạng Shorts 9:16: {err}")

        output_path.replace(input_path)
        duration, width, height = _probe(input_path)
        new_size = input_path.stat().st_size

        file_info['duration'] = duration
        file_info['width'] = width
        file_info['height'] = height
        file_info['size'] = new_size
        return file_info
    except subprocess.TimeoutExpired as exc:
        output_path.unlink(missing_ok=True)
        raise DownloadError('Quá thời gian chuyển đổi video sang định dạng Shorts 9:16.') from exc


def download_tiktok_video(settings, source_url):
    """Download within bounded disk/time limits and return one unpublished media row."""
    url = validate_tiktok_url(source_url)
    root = settings.data_dir / 'media'
    root.mkdir(parents=True, exist_ok=True)
    media_id = new_id()
    file = root / f'{media_id}.mp4'
    succeeded = False
    max_bytes = settings.max_upload_mb * 1024**2
    try:
        existing_bytes = sum(p.stat().st_size for p in root.iterdir() if p.is_file())
        if existing_bytes >= settings.max_storage_mb * 1024**2 - max_bytes:
            raise DownloadError('Dung lượng lưu video trên VPS không đủ.')
        command = [
            sys.executable, '-m', 'yt_dlp',
            '--ignore-config', '--no-playlist', '--no-cache-dir', '--no-progress',
            '--write-info-json', '--no-write-thumbnail', '--no-write-subs',
            '--socket-timeout', '15', '--retries', '1', '--fragment-retries', '1',
            '--max-filesize', str(max_bytes), '--format', 'b[ext=mp4]/b',
            '--recode-video', 'mp4',
            '--output', str(root / f'{media_id}.%(ext)s'),
            '--', url,
        ]
        # Do not add user-provided arguments or pass a shell command.
        process = subprocess.run(command, capture_output=True, timeout=200, check=False)
        if process.returncode != 0 or not file.is_file():
            raise DownloadError('TikTok không cung cấp video tải được qua bộ xử lý.')
        size = file.stat().st_size
        if size <= 0 or size > max_bytes:
            raise DownloadError('Video vượt giới hạn hoặc không có dữ liệu.')
        if existing_bytes + size > settings.max_storage_mb * 1024**2:
            raise DownloadError('Dung lượng VPS vượt giới hạn.')
        duration, width, height = _probe(file)
        metadata = {}
        info_file = root / f'{media_id}.info.json'
        if info_file.is_file() and info_file.stat().st_size <= 8 * 1024**2:
            try:
                info = json.loads(info_file.read_text(encoding='utf-8'))
                metadata = source_metadata(info)
            except (ValueError, OSError, TypeError):
                pass
        succeeded = True
        return {
            'id': media_id, 'filename': f'{media_id}.mp4', 'path': str(file.resolve()),
            'size': size, 'duration': duration, 'width': width, 'height': height,
            'created_at': time.time(), 'source_metadata': metadata,
        }
    except subprocess.TimeoutExpired as exc:
        raise DownloadError('Quá thời gian tải video TikTok.') from exc
    finally:
        # Remove temporary/failed downloads. On success keep only the final MP4.
        for candidate in root.glob(f'{media_id}.*'):
            if candidate != file:
                candidate.unlink(missing_ok=True)
        if not succeeded:
            file.unlink(missing_ok=True)


def source_metadata(info):
    """Keep only public publishing text, never extractor URLs/headers/cookies."""
    if not isinstance(info, dict):
        return {}
    def clean(value, limit):
        if not isinstance(value, str):
            return ''
        return ''.join(c for c in value if c >= ' ' or c == '\n').replace('<', '').replace('>', '').strip()[:limit]
    description = clean(info.get('description'), 5000)
    title = clean(info.get('title'), 100) or clean(description.split('\n')[0], 100)
    candidates = info.get('tags') if isinstance(info.get('tags'), list) else []
    candidates = candidates + re.findall(r'(?<!\w)#([\w]+)', description)
    tags, seen, budget = [], set(), 0
    for value in candidates:
        tag = clean(value, 80).lstrip('#')
        cost = len(tag) + (2 if ' ' in tag else 0) + 1
        if tag and tag.casefold() not in seen and budget + cost <= 450:
            tags.append(tag)
            seen.add(tag.casefold())
            budget += cost
    return {'title': title, 'description': description, 'tags': tags}
