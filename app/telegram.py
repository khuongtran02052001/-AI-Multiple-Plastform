from __future__ import annotations
"""Telegram bot notification helper for publisher workflow with colored progress."""
import logging
from html import escape
import httpx

logger = logging.getLogger('publisher.telegram')


def get_colored_progress_bar(percent: int, total_blocks: int = 10) -> str:
    filled = max(0, min(total_blocks, int(round(percent / (100 / total_blocks)))))
    empty = total_blocks - filled
    return '🟩' * filled + '⬜' * empty


def build_status_message(source_url: str, label: str, percent: int, step_index: int,
                         file_info: str = '', video_title: str = '',
                         youtube_url: str = '', facebook_url: str = '',
                         target_platform: str = 'youtube', error_message: str = '') -> str:
    source_url, label, file_info, video_title, youtube_url, facebook_url, error_message = (
        escape(str(v), quote=True) for v in (source_url, label, file_info, video_title, youtube_url, facebook_url, error_message)
    )
    if target_platform == 'facebook':
        step3_name = 'Tối ưu video chuẩn Facebook Page'
        step4_name = 'Đăng lên Facebook Page'
    elif target_platform == 'both':
        step3_name = 'Tối ưu chuẩn Shorts 9:16 & Reels'
        step4_name = 'Đăng lên YouTube Studio & Facebook Page'
    else:
        step3_name = 'Tối ưu chuẩn Shorts 9:16 & thẻ #Shorts' if 'Short' in label else 'Tối ưu định dạng & thẻ video'
        step4_name = 'Đăng lên YouTube Studio'

    if file_info and step_index >= 3:
        step3_name += f' ({file_info})'

    steps = [
        'Tiếp nhận & xếp hàng xử lý',
        'Tải video TikTok về VPS',
        step3_name,
        step4_name,
    ]

    if error_message:
        bar = '🟥' * 10
        return (
            f"❌ <b>XUẤT BẢN THẤT BẠI [{label}]</b>\n"
            f"🔗 {source_url}\n\n"
            f"Tiến độ: {bar} <b>LỖI</b>\n\n"
            f"⚠️ <b>Chi tiết lỗi:</b> {error_message}\n\n"
            f"📋 <b>Xem chi tiết:</b> <a href='https://publisher.toomi.vn/'>Trung tâm tác vụ</a>"
        )

    bar = get_colored_progress_bar(percent)
    step_lines = []
    for i, step_name in enumerate(steps, start=1):
        if i < step_index:
            step_lines.append(f"🟢 {step_name}")
        elif i == step_index:
            if percent >= 100:
                step_lines.append(f"🟢 {step_name}")
            else:
                step_lines.append(f"🟡 {step_name}...")
        else:
            step_lines.append(f"⚪ {step_name}")

    steps_block = '\n'.join(step_lines)

    if percent >= 100:
        title_line = f"\n\n🎬 <b>Tiêu đề:</b> {video_title}" if video_title else ''
        links = []
        if youtube_url:
            links.append(f"👉 <b>YouTube:</b> <a href='{youtube_url}'>{youtube_url}</a>")
        if facebook_url:
            links.append(f"👉 <b>Facebook Page:</b> <a href='{facebook_url}'>{facebook_url}</a>")
        links_block = ('\n' + '\n'.join(links)) if links else ''
        return (
            f"🎉 <b>XUẤT BẢN THÀNH CÔNG [{label}]</b>\n"
            f"🔗 {source_url}\n\n"
            f"Tiến độ: {bar} <b>100%</b>\n\n"
            f"{steps_block}"
            f"{title_line}"
            f"{links_block}\n"
            f"📋 <b>Quản lý tác vụ:</b> <a href='https://publisher.toomi.vn/'>Trung tâm tác vụ</a>"
        )

    return (
        f"⏳ <b>ĐANG XỬ LÝ [{label}]</b>\n"
        f"🔗 {source_url}\n\n"
        f"Tiến độ: {bar} <b>{percent}%</b>\n\n"
        f"{steps_block}\n\n"
        f"📋 <b>Theo dõi tại:</b> <a href='https://publisher.toomi.vn/'>Trung tâm tác vụ</a>"
    )


def update_telegram_progress(token: str, chat_id: str | None, message_id: str | int | None,
                             source_url: str, label: str, percent: int, step_index: int,
                             file_info: str = '', video_title: str = '',
                             youtube_url: str = '', facebook_url: str = '',
                             target_platform: str = 'youtube', error_message: str = ''):
    if not token or not chat_id or not message_id:
        return False
    try:
        text = build_status_message(
            source_url=source_url,
            label=label,
            percent=percent,
            step_index=step_index,
            file_info=file_info,
            video_title=video_title,
            youtube_url=youtube_url,
            facebook_url=facebook_url,
            target_platform=target_platform,
            error_message=error_message
        )
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        payload = {
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(url, json=payload)
            if resp.is_error:
                logger.warning("Telegram editMessageText failed (HTTP %s)", resp.status_code)
                return False
            return resp.json().get("ok") is True
    except Exception as e:
        logger.warning("Could not update Telegram message.")
        return False
