from datetime import datetime, timezone
from .api import ApiError, AuthRequired, RateLimited


def normalize(sid, position, song_id, song, privilege, stamp):
    artists = [a.get('name') for a in song.get('ar', song.get('artists', [])) if a.get('name')]
    album = song.get('al', song.get('album', {})) or {}
    duration = song.get('dt', song.get('duration'))
    published = song.get('publishTime') or album.get('publishTime')
    release = None
    if isinstance(published, (int, float)) and published > 0:
        try:
            release = datetime.fromtimestamp(published / 1000, timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    status = 'unknown'
    if not song:
        status = 'metadata_unavailable'
    elif privilege:
        if privilege.get('st', 0) < 0:
            status = 'unavailable_or_restricted'
        elif privilege.get('pl', 0) > 0:
            status = 'playable_for_current_session'
        elif privilege.get('fee') in (1, 4, 8):
            status = 'requires_subscription_or_purchase'
        elif privilege.get('pl') == 0:
            status = 'restricted_for_current_session'
    return dict(playlist_id=str(sid), position=position, song_id=str(song_id),
                title=song.get('name') or None, artists=artists or None, primary_artist=artists[0] if artists else None,
                album=album.get('name') or None, album_id=str(album['id']) if album.get('id') else None,
                duration_ms=duration, duration_seconds=duration / 1000 if duration is not None else None,
                release_date=release, track_number=song.get('no') or None, disc_number=song.get('cd') or None,
                song_url=f'https://music.163.com/song?id={song_id}', cover_url=album.get('picUrl'),
                availability=status, exported_at=stamp,
                aliases=song.get('alia', []), translations=song.get('tns', []),
                main_title=song.get('mainTitle'), additional_title=song.get('additionalTitle'),
                raw_song=song, raw_privilege=privilege)


class PlaylistService:
    def __init__(self, api, progress=lambda text: None):
        self.api, self.progress = api, progress

    def collect(self, sid):
        for snapshot_attempt in range(2):
            p = self.api.playlist(sid)
            ids = self.ids(p)
            # Retry truncated ID lists before attempting details.
            for _ in range(2):
                if len(ids) == p['trackCount']:
                    break
                self.progress('歌曲 ID 数量与平台总数不一致，重新读取歌单…')
                p = self.api.playlist(sid)
                ids = self.ids(p)
            songs, privileges, errors = {}, {}, []
            wanted = list(dict.fromkeys(ids))
            for round_no in range(3):
                missing = [i for i in wanted if i not in songs or self.missing_core(songs[i])]
                if not missing:
                    break
                for start in range(0, len(missing), 50):
                    batch = missing[start:start + 50]
                    self.progress(f'歌单 {sid}：补齐详情 {min(start + 50, len(missing))}/{len(missing)}（第 {round_no + 1} 轮）')
                    try:
                        data = self.api.songs(batch)
                    except (AuthRequired, RateLimited):
                        raise
                    except ApiError as e:
                        errors.append(str(e))
                        continue
                    for song in data['songs']:
                        key = str(song.get('id'))
                        if key in batch:
                            songs[key] = song
                    for privilege in data.get('privileges', []):
                        privileges[str(privilege.get('id'))] = privilege
            end = self.api.playlist(sid)
            changed = (self.ids(end) != ids or end['trackCount'] != p['trackCount'] or
                       end.get('trackUpdateTime') != p.get('trackUpdateTime'))
            if changed and snapshot_attempt == 0:
                self.progress('导出期间歌单发生变更，重新获取一致快照…')
                continue
            stamp = datetime.now().astimezone().isoformat(timespec='seconds')
            rows = [normalize(sid, pos, i, songs.get(i, {}), privileges.get(i), stamp)
                    for pos, i in enumerate(ids, 1)]
            missing_rows = [{'position': r['position'], 'song_id': r['song_id'],
                             'fields': self.missing_core(songs.get(r['song_id'], {}))}
                            for r in rows if self.missing_core(songs.get(r['song_id'], {}))]
            report = dict(complete=len(ids) == p['trackCount'] and not missing_rows and not changed,
                          expected_count=p['trackCount'], exported_count=len(rows),
                          metadata_complete_count=len(rows) - len(missing_rows),
                          missing_id_count=max(0, p['trackCount'] - len(ids)),
                          missing_records=missing_rows, snapshot_changed=changed,
                          request_errors=list(dict.fromkeys(errors)), exported_at=stamp)
            # Do not include unrelated creator account fields returned by the platform.
            meta = {k: p.get(k) for k in ('id', 'name', 'coverImgUrl', 'trackCount', 'description', 'tags',
                                          'createTime', 'updateTime', 'trackUpdateTime', 'privacy')}
            meta['creator'] = {k: (p.get('creator') or {}).get(k) for k in ('userId', 'nickname')}
            return dict(schema_version=1, playlist=meta, exported_at=stamp, report=report, tracks=rows)

    @staticmethod
    def ids(p):
        values = p.get('trackIds')
        if not isinstance(values, list):
            # Never substitute the possibly truncated tracks preview for the authoritative ID list.
            return []
        if any(not isinstance(x, dict) or not str(x.get('id', '')).isdecimal() for x in values):
            raise ApiError('歌单歌曲 ID 列表含无效记录。')
        return [str(x['id']) for x in values]

    @staticmethod
    def missing_core(song):
        missing = []
        for field, value in [('title', song.get('name')), ('artists', song.get('ar', song.get('artists'))),
                             ('album', (song.get('al', song.get('album')) or {}).get('name')),
                             ('duration_ms', song.get('dt', song.get('duration')))]:
            if value is None or value == '' or value == []:
                missing.append(field)
        return missing
