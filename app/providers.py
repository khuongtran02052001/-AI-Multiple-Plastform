"""Direct official APIs only. No Upload-Post, cookies or browser automation."""
import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
import httpx
from app.security import safe_error


class PublishError(Exception):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class Providers:
    def __init__(self, settings, client=None):
        self.s = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(120, connect=15), follow_redirects=False)

    def available(self, provider):
        if provider == 'youtube':
            return bool(self.s.google_client_id and self.s.google_client_secret)
        if provider == 'facebook':
            return bool(self.s.meta_app_id and self.s.meta_app_secret)
        if provider == 'tiktok':
            return bool(self.s.tiktok_client_key and self.s.tiktok_client_secret)
        return False

    def callback(self, provider):
        return f'{self.s.base_url}/oauth/{provider}/callback'

    def authorize_url(self, provider, state, verifier):
        if provider == 'youtube':
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
                'client_id': self.s.google_client_id, 'redirect_uri': self.callback(provider),
                'response_type': 'code', 'scope': 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
                'access_type': 'offline', 'prompt': 'consent', 'state': state,
                'code_challenge': challenge, 'code_challenge_method': 'S256'})
        if provider == 'facebook':
            return f'https://www.facebook.com/{self.s.meta_api_version}/dialog/oauth?' + urlencode({
                'client_id': self.s.meta_app_id, 'redirect_uri': self.callback(provider),
                'response_type': 'code', 'state': state,
                'scope': 'pages_show_list,pages_read_engagement,pages_manage_posts'})
        if provider == 'tiktok':
            return 'https://www.tiktok.com/v2/auth/authorize/?' + urlencode({
                'client_key': self.s.tiktok_client_key,
                'scope': 'user.info.basic,video.upload,video.publish',
                'response_type': 'code',
                'redirect_uri': self.callback(provider),
                'state': state})
        raise PublishError('Nền tảng không được hỗ trợ.')

    def request_json(self, method, url, *, mutation=False, allow_empty=False, **kwargs):
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise PublishError('Mất kết nối với nền tảng; cần kiểm tra kết quả trên tài khoản.'
                               if mutation else 'Không thể kết nối API nền tảng.', uncertain=mutation)
        if allow_empty and not response.content and response.is_success:
            return {}, response
        try:
            result = response.json()
        except ValueError:
            raise PublishError(f'API trả phản hồi không đọc được (HTTP {response.status_code}).', uncertain=mutation)
        if response.is_error or (isinstance(result, dict) and result.get('error')):
            error = result.get('error', {}) if isinstance(result, dict) else {}
            message = error.get('message', '') if isinstance(error, dict) else str(error)
            code = error.get('code', response.status_code) if isinstance(error, dict) else response.status_code
            raise PublishError(safe_error(f'API {code}: {message or "Yêu cầu bị từ chối"}'),
                               uncertain=mutation and response.status_code >= 500)
        if not isinstance(result, dict):
            raise PublishError('API trả cấu trúc không hợp lệ.', uncertain=mutation)
        return result, response

    def exchange(self, provider, code, verifier):
        if provider == 'youtube':
            tokens, _ = self.request_json('POST', 'https://oauth2.googleapis.com/token', data={
                'client_id': self.s.google_client_id, 'client_secret': self.s.google_client_secret,
                'code': code, 'code_verifier': verifier, 'grant_type': 'authorization_code',
                'redirect_uri': self.callback(provider)})
            if not tokens.get('refresh_token'):
                raise PublishError('Google chưa cấp refresh token. Ngắt quyền cũ rồi kết nối lại với consent.')
            tokens['expires_at'] = time.time() + int(tokens.get('expires_in', 3600))
            channels, _ = self.request_json('GET', 'https://www.googleapis.com/youtube/v3/channels',
                headers={'Authorization': f'Bearer {tokens["access_token"]}'},
                params={'part': 'snippet', 'mine': 'true'})
            items = channels.get('items', [])
            if len(items) != 1:
                raise PublishError('Cần chọn đúng một kênh YouTube trong bước cấp quyền Google.')
            channel = items[0]
            return [{'external_id': channel['id'], 'name': channel['snippet']['title'], 'tokens': tokens}]
        if provider == 'tiktok':
            tokens, _ = self.request_json('POST', 'https://open.tiktokapis.com/v2/oauth/token/', data={
                'client_key': self.s.tiktok_client_key,
                'client_secret': self.s.tiktok_client_secret,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': self.callback(provider)})
            data = tokens.get('data', tokens)
            access_token = data.get('access_token')
            if not access_token:
                err_msg = tokens.get('error', {}).get('message', 'Không lấy được access token từ TikTok.')
                raise PublishError(f'TikTok OAuth lỗi: {err_msg}')
            user_info, _ = self.request_json('GET',
                'https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,avatar_url',
                headers={'Authorization': f'Bearer {access_token}'})
            user_data = user_info.get('data', {}).get('user', {})
            external_id = user_data.get('open_id') or data.get('open_id')
            display_name = user_data.get('display_name') or 'Tài khoản TikTok'
            token_store = {
                'access_token': access_token,
                'refresh_token': data.get('refresh_token'),
                'open_id': external_id,
                'expires_at': time.time() + int(data.get('expires_in', 86400)),
                'refresh_expires_at': time.time() + int(data.get('refresh_expires_in', 31536000))
            }
            return [{'external_id': external_id, 'name': display_name, 'tokens': token_store}]
        graph = f'https://graph.facebook.com/{self.s.meta_api_version}'
        token, _ = self.request_json('GET', f'{graph}/oauth/access_token', params={
            'client_id': self.s.meta_app_id, 'client_secret': self.s.meta_app_secret,
            'redirect_uri': self.callback(provider), 'code': code})
        extended, _ = self.request_json('GET', f'{graph}/oauth/access_token', params={
            'grant_type': 'fb_exchange_token', 'client_id': self.s.meta_app_id,
            'client_secret': self.s.meta_app_secret, 'fb_exchange_token': token['access_token']})
        access = extended['access_token']
        params = {'access_token': access, 'appsecret_proof': self.proof(access),
                  'fields': 'id,name,access_token,tasks', 'limit': 100}
        found = []
        for _ in range(10):
            result, _ = self.request_json('GET', f'{graph}/me/accounts', params=params)
            for page in result.get('data', []):
                if page.get('access_token'):
                    found.append({'external_id': page['id'], 'name': page['name'],
                        'tokens': {'access_token': page['access_token'], 'kind': 'page'}})
            after = result.get('paging', {}).get('cursors', {}).get('after')
            if not result.get('paging', {}).get('next') or not after:
                break
            params['after'] = after
        if not found:
            raise PublishError('Không tìm thấy Page được cấp quyền. Kiểm tra quyền và tài khoản quản trị Trang.')
        return found

    def proof(self, token):
        return hmac.new(self.s.meta_app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()

    def refresh_youtube(self, tokens):
        if tokens.get('expires_at', 0) > time.time() + 90:
            return tokens
        if not tokens.get('refresh_token'):
            raise PublishError('Thiếu refresh token. Kết nối lại YouTube.')
        fresh, _ = self.request_json('POST', 'https://oauth2.googleapis.com/token', data={
            'client_id': self.s.google_client_id, 'client_secret': self.s.google_client_secret,
            'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token']})
        return {**tokens, **fresh, 'expires_at': time.time() + int(fresh.get('expires_in', 3600))}

    def refresh_tiktok(self, tokens):
        if tokens.get('expires_at', 0) > time.time() + 90:
            return tokens
        if not tokens.get('refresh_token'):
            raise PublishError('Thiếu refresh token. Kết nối lại TikTok.')
        fresh, _ = self.request_json('POST', 'https://open.tiktokapis.com/v2/oauth/token/', data={
            'client_key': self.s.tiktok_client_key,
            'client_secret': self.s.tiktok_client_secret,
            'grant_type': 'refresh_token',
            'refresh_token': tokens['refresh_token']
        })
        data = fresh.get('data', fresh)
        return {
            **tokens,
            'access_token': data.get('access_token', tokens['access_token']),
            'refresh_token': data.get('refresh_token', tokens.get('refresh_token')),
            'expires_at': time.time() + int(data.get('expires_in', 86400))
        }

    def publish(self, account, tokens, post, file):
        if account['provider'] == 'tiktok':
            if not file:
                raise PublishError('TikTok yêu cầu video.')
            tokens = self.refresh_tiktok(tokens)
            tags_list = json.loads(post['tags']) if post.get('tags') else []
            hashtags_str = ' '.join(f'#{t.lstrip("#")}' for t in tags_list)
            full_title = f"{post['title']} {hashtags_str}".strip()[:150]
            privacy_level = 'PUBLIC_TO_EVERYONE' if post['privacy'] == 'public' else 'SELF_ONLY'
            init_payload = {
                'post_info': {
                    'title': full_title,
                    'privacy_level': privacy_level,
                    'disable_duet': False,
                    'disable_stitch': False,
                    'disable_comment': False
                },
                'source_info': {
                    'source': 'FILE_UPLOAD',
                    'video_size': file['size'],
                    'chunk_size': file['size'],
                    'total_chunk_count': 1
                }
            }
            init_res, _ = self.request_json('POST',
                'https://open.tiktokapis.com/v2/post/publish/video/init/',
                headers={'Authorization': f'Bearer {tokens["access_token"]}',
                         'Content-Type': 'application/json; charset=UTF-8'},
                json=init_payload)
            init_data = init_res.get('data', {})
            publish_id = init_data.get('publish_id')
            upload_url = init_data.get('upload_url')
            if not upload_url or not publish_id:
                err_msg = init_res.get('error', {}).get('message', 'Không tạo được phiên upload TikTok.')
                raise PublishError(f'Lỗi khởi tạo upload TikTok: {err_msg}')

            with Path(file['path']).open('rb') as stream:
                self.client.put(upload_url, headers={
                    'Content-Type': 'video/mp4',
                    'Content-Length': str(file['size']),
                    'Content-Range': f'bytes 0-{file["size"] - 1}/{file["size"]}'
                }, content=stream)

            return str(publish_id), f'https://www.tiktok.com/@{account["name"]}'

        if account['provider'] == 'youtube':
            if not file:
                raise PublishError('YouTube yêu cầu video.')
            metadata = {'snippet': {'title': post['title'], 'description': post['description'],
                'tags': json.loads(post['tags']), 'categoryId': '22'},
                'status': {'privacyStatus': post['privacy'], 'selfDeclaredMadeForKids': post['made_for_kids']}}
            result, response = self.request_json('POST',
                'https://www.googleapis.com/upload/youtube/v3/videos', allow_empty=True,
                headers={'Authorization': f'Bearer {tokens["access_token"]}',
                         'X-Upload-Content-Type': 'video/mp4', 'X-Upload-Content-Length': str(file['size'])},
                params={'uploadType': 'resumable', 'part': 'snippet,status'}, json=metadata)
            upload_url = response.headers.get('location', '')
            parsed = urlparse(upload_url)
            if parsed.scheme != 'https' or parsed.hostname != 'www.googleapis.com':
                raise PublishError('YouTube không trả URL upload hợp lệ.')
            with Path(file['path']).open('rb') as stream:
                result, _ = self.request_json('PUT', upload_url, mutation=True,
                    headers={'Authorization': f'Bearer {tokens["access_token"]}',
                             'Content-Type': 'video/mp4', 'Content-Length': str(file['size'])}, content=stream)
            remote_id = result.get('id')
            if not remote_id:
                raise PublishError('YouTube chưa trả video ID; kiểm tra kênh trước khi đăng lại.', uncertain=True)
            return str(remote_id), f'https://www.youtube.com/watch?v={remote_id}'
        if tokens.get('kind') != 'page':
            raise PublishError('Facebook yêu cầu Page Access Token.')
        graph = f'https://graph.facebook.com/{self.s.meta_api_version}'
        data = {'access_token': tokens['access_token'], 'appsecret_proof': self.proof(tokens['access_token'])}
        if file:
            data.update({'title': post['title'], 'description': post['description']})
            with Path(file['path']).open('rb') as stream:
                result, _ = self.request_json('POST', f'{graph}/{account["external_id"]}/videos',
                    mutation=True, data=data, files={'source': ('video.mp4', stream, 'video/mp4')})
        else:
            data['message'] = '\n\n'.join(x for x in [post['title'], post['description']] if x)
            result, _ = self.request_json('POST', f'{graph}/{account["external_id"]}/feed', mutation=True, data=data)
        remote_id = result.get('id')
        if not remote_id:
            raise PublishError('Facebook chưa trả bài ID; kiểm tra Trang trước khi đăng lại.', uncertain=True)
        return str(remote_id), f'https://www.facebook.com/{remote_id}'

    def close(self):
        self.client.close()
