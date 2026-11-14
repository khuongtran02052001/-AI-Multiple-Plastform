from app.telegram import build_status_message, update_telegram_progress


def test_telegram_escapes_untrusted_caption():
    text = build_status_message('https://www.tiktok.com/test', 'Test', 100, 4,
                                video_title='<b>not markup</b> & caption')
    assert '&lt;b&gt;not markup&lt;/b&gt; &amp; caption' in text
    assert '<b>not markup</b>' not in text


def test_notification_only_confirms_actual_api_success(monkeypatch, caplog):
    import app.telegram as telegram
    class Response:
        status_code = 200
        is_error = False
        def json(self): return {'ok': True}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs): return Response()
    monkeypatch.setattr(telegram.httpx, 'Client', Client)
    assert update_telegram_progress('', '1', '2', '', '', 100, 4) is False
    assert update_telegram_progress('test-token', '1', '2', '', '', 100, 4) is True
    Response.is_error = True
    Response.status_code = 500
    assert update_telegram_progress('test-token', '1', '2', '', '', 100, 4) is False
    assert 'test-token' not in caplog.text


def test_telegram_status_message_multi_platform():
    # Facebook test
    fb_text = build_status_message('https://www.tiktok.com/test', '🔵 Facebook Reels', 100, 4,
                                   video_title='FB Video', facebook_url='https://www.facebook.com/12345',
                                   target_platform='facebook')
    assert 'Facebook Page' in fb_text
    assert 'https://www.facebook.com/12345' in fb_text
    assert 'YouTube Studio' not in fb_text

    # Both platforms test
    both_text = build_status_message('https://www.tiktok.com/test', '🚀 YouTube & Facebook', 100, 4,
                                     video_title='Multi Video',
                                     youtube_url='https://www.youtube.com/shorts/abc',
                                     facebook_url='https://www.facebook.com/67890',
                                     target_platform='both')
    assert 'YouTube Studio & Facebook Page' in both_text
    assert 'https://www.youtube.com/shorts/abc' in both_text
    assert 'https://www.facebook.com/67890' in both_text
