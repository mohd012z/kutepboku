import json
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import suno_scout
from suno_scout import (download_audio, extract_suno_link, fetch_song_info,
                        link_only_card, looks_like_suno_link, song_card,
                        suno_menu, suno_study, _schema_from_html, _valid_audio)


def esc(o):
    """Embed ``o`` the way Suno does: JSON escaped inside the RSC payload."""
    return json.dumps(o, ensure_ascii=False).replace('"', '\\"')


def make_schema(content_id, **overrides):
    base = {
        "status": "complete",
        "title": "Test Song",
        "display_name": "An Artist",
        "handle": "anartist",
        "id": content_id,
        "entity_type": "song_schema",
        "video_url": "",
        "audio_url": "https://studio-api.prod.suno.com/api/forbidden",
        "media_urls": [{"url": "https://d2lwuy8qc234o3.cloudfront.net/1/clip/"
                                + content_id + ".m4a",
                        "content_type": "m4a-opus",
                        "delivery": "progressive"}],
        "image_url": "https://cdn2.suno.ai/image_" + content_id + ".jpeg",
        "image_large_url": "https://cdn2.suno.ai/image_large_" + content_id + ".jpeg",
        "model_name": "chirp-goose",
        "metadata": {"tags": "lo-fi, chill beats, soft female vocal",
                     "duration": 90, "status": "complete"},
    }
    base.update(overrides)
    return base


CID = "992139a6-22c6-4c8c-a83b-1069506b9330"


class ExtractLinkTests(unittest.TestCase):
    def test_share_code(self):
        self.assertEqual(extract_suno_link("https://suno.com/s/WxZwWbtM8cb5G48P"),
                         "https://suno.com/s/WxZwWbtM8cb5G48P")

    def test_share_code_in_sentence(self):
        self.assertEqual(
            extract_suno_link("here you go https://suno.com/s/ABCdef123456 thanks"),
            "https://suno.com/s/ABCdef123456")

    def test_song_uuid(self):
        self.assertEqual(
            extract_suno_link("https://suno.com/song/" + CID),
            "https://suno.com/song/" + CID)

    def test_bare_uuid(self):
        self.assertEqual(extract_suno_link(CID), "https://suno.com/song/" + CID)

    def test_bare_code(self):
        self.assertEqual(extract_suno_link("WxZwWbtM8cb5G48P"),
                         "https://suno.com/s/WxZwWbtM8cb5G48P")

    def test_none_for_non_suno(self):
        for bad in ("", "   ", "https://github.com/mohd012z/kutepboku",
                    "suno.com (no path)", "https://example.com/s/short",
                    "https://suno.com/s/s"):  # 's' code too short
            self.assertIsNone(extract_suno_link(bad))

    def test_looks_like(self):
        self.assertTrue(looks_like_suno_link("https://suno.com/s/AbC1234567890"))
        self.assertFalse(looks_like_suno_link("quantum computing"))


class SchemaParseTests(unittest.TestCase):
    def test_parses_embedded_schema(self):
        html = "<head>...</head><script>...," + esc(make_schema(CID)) + \
               ",more</script>"
        info = _schema_from_html(html)
        self.assertIsNotNone(info)
        self.assertEqual(info["title"], "Test Song")
        self.assertEqual(info["artist"], "An Artist")
        self.assertEqual(info["handle"], "anartist")
        self.assertIn("lo-fi", info["style"])
        self.assertEqual(info["duration"], 90.0)
        self.assertEqual(info["media_url"],
                         "https://d2lwuy8qc234o3.cloudfront.net/1/clip/" + CID + ".m4a")
        self.assertTrue(info["cover_url"].endswith(".jpeg"))
        self.assertEqual(info["share_url"], "https://suno.com/song/" + CID)

    def test_unicode_title(self):
        html = esc(make_schema(CID, title="रूखी माँ"))
        self.assertEqual(_schema_from_html(html)["title"], "रूखी माँ")

    def test_no_schema_returns_none(self):
        self.assertIsNone(_schema_from_html("<html>no song here</html>"))
        self.assertIsNone(_schema_from_html(""))
        self.assertIsNone(_schema_from_html(None))

    def test_media_url_fallback_regex(self):
        # schema object missing media_urls but the CDN url is elsewhere on page
        schema = make_schema(CID)
        del schema["media_urls"]
        html = esc(schema) + ' ... "https://d2lwuy8qc234o3.cloudfront.net/' \
                             '1/clip/' + CID + '.m4a" ...'
        info = _schema_from_html(html)
        self.assertIsNotNone(info)
        self.assertIn("cloudfront.net", info["media_url"] or "")

    def test_field_fallback_when_object_parse_breaks(self):
        # Truncate the object mid-way so raw_decode fails -> per-field regex.
        full = esc(make_schema(CID))
        broken = full[:len(full) // 2] + 'garbage'
        html = broken
        info = _schema_from_html(html)
        self.assertIsNotNone(info)
        self.assertEqual(info["content_id"], CID)


class FetchSongInfoTests(unittest.TestCase):
    def _session(self, text, status=200):
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = status
        resp.text = text
        resp.raise_for_status = MagicMock()
        client.get = MagicMock(return_value=resp)
        return client

    def test_not_found_raises(self):
        html = "<html><div>Song not found</div></html>"
        with self.assertRaises(ValueError):
            fetch_song_info("https://suno.com/s/zzzzzzzzzzzzzzzz",
                            session=self._session(html))

    def test_no_schema_raises(self):
        with self.assertRaises(ValueError):
            fetch_song_info("https://suno.com/s/AbCdef123456",
                            session=self._session("<html>plain page</html>"))

    def test_success(self):
        html = esc(make_schema(CID))
        info = fetch_song_info("https://suno.com/s/WxZwWbtM8cb5G48P",
                               session=self._session(html))
        self.assertEqual(info["title"], "Test Song")

    def test_generating_note(self):
        schema = make_schema(CID, status="generating")
        info = fetch_song_info("https://suno.com/s/AbCdef123456",
                               session=self._session(esc(schema)))
        self.assertEqual(info["status"], "generating")
        self.assertIn("note", info)


class DownloadAudioTests(unittest.TestCase):
    def test_returns_valid_file(self):
        info = {"share_url": "https://suno.com/song/" + CID,
                "title": "Test Song"}
        m4a = b"\x00\x00\x00\x1cftypisom" + b"\x00" * 500  # ftyp within 16 bytes
        client = MagicMock()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json = MagicMock(return_value={
            "download_url": "/downloads/test.m4a", "filename": "Test.m4a"})
        file_resp = MagicMock()
        file_resp.status_code = 200
        file_resp.raise_for_status = MagicMock()
        file_resp.iter_content = lambda n: iter([m4a])
        client.post = MagicMock(return_value=post_resp)
        client.get = MagicMock(return_value=file_resp)
        filename, audio = download_audio(info, "m4a", session=client)
        self.assertEqual(filename, "Test.m4a")
        self.assertEqual(audio, m4a)
        # POST body: the share url + chosen format
        _, kwargs = client.post.call_args
        self.assertEqual(kwargs["json"]["format"], "m4a")

    def test_api_error_raises(self):
        info = {"share_url": "https://suno.com/song/" + CID, "title": "t"}
        client = MagicMock()
        post_resp = MagicMock()
        post_resp.status_code = 500
        post_resp.json = MagicMock(return_value={"error": "boom"})
        client.post = MagicMock(return_value=post_resp)
        with self.assertRaises(ValueError):
            download_audio(info, "mp3", session=client)

    def test_too_large_raises(self):
        info = {"share_url": "https://suno.com/song/" + CID, "title": "t"}
        big = b"\x00\x00\x00\x1cftyp" + b"\x00" * (suno_scout.AUDIO_MAX_BYTES + 10)
        client = MagicMock()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json = MagicMock(return_value={
            "download_url": "/x", "filename": "t.wav"})
        file_resp = MagicMock()
        file_resp.raise_for_status = MagicMock()
        file_resp.iter_content = lambda n: iter([big])
        client.post = MagicMock(return_value=post_resp)
        client.get = MagicMock(return_value=file_resp)
        with self.assertRaises(ValueError):
            download_audio(info, "wav", session=client)

    def test_invalid_signature_raises(self):
        info = {"share_url": "https://suno.com/song/" + CID, "title": "t"}
        client = MagicMock()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json = MagicMock(return_value={
            "download_url": "/x", "filename": "t.m4a"})
        file_resp = MagicMock()
        file_resp.raise_for_status = MagicMock()
        file_resp.iter_content = lambda n: iter([b"\xff" * 1000])
        client.post = MagicMock(return_value=post_resp)
        client.get = MagicMock(return_value=file_resp)
        with self.assertRaises(ValueError):
            download_audio(info, "m4a", session=client)


class ValidAudioTests(unittest.TestCase):
    def test_m4a_needs_ftyp(self):
        self.assertTrue(_valid_audio(b"\x00\x00\x00\x1cftyp" + b"\x00" * 300, "m4a"))
        self.assertFalse(_valid_audio(b"xxxx" * 100, "m4a"))
        self.assertFalse(_valid_audio(b"ftyp" * 50, "m4a"))  # too small

    def test_mp3(self):
        self.assertTrue(_valid_audio(b"ID3" + b"\x00" * 400, "mp3"))
        self.assertTrue(_valid_audio(b"\xff\xfb" + b"\x00" * 400, "mp3"))
        self.assertFalse(_valid_audio(b"zzzz" * 100, "mp3"))

    def test_wav(self):
        self.assertTrue(_valid_audio(b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 400, "wav"))
        self.assertFalse(_valid_audio(b"RIFF" + b"\x00" * 400, "wav"))


class CardTests(unittest.TestCase):
    def test_song_card_shape(self):
        info = {"title": "Song", "artist": "Artist", "style": "tags",
                "duration": 90, "model": "chirp-goose",
                "share_url": "https://suno.com/song/" + CID}
        card = song_card(info)
        self.assertIn("Song", card["text"])
        self.assertIn("1:30", card["text"])
        rows = card["reply_markup"]["inline_keyboard"]
        data = [b["callback_data"] for row in rows for b in row
                if "callback_data" in b]
        self.assertIn("snu:dl:m4a", data)
        self.assertIn("snu:dl:mp3", data)
        self.assertIn("snu:link", data)
        self.assertIn("ui:home", data)
        # an url button for "open on suno"
        self.assertTrue(any("url" in b and "suno.com" in b["url"]
                            for row in rows for b in row))

    def test_link_only_card(self):
        info = {"title": "Song", "artist": "Artist",
                "media_url": "https://cdn/x.m4a",
                "share_url": "https://suno.com/song/" + CID}
        card = link_only_card(info)
        self.assertIn("decrypt service is unreachable", card["text"])
        self.assertIn("https://cdn/x.m4a", card["text"])
        data = [b["callback_data"]
                for row in card["reply_markup"]["inline_keyboard"] for b in row]
        self.assertIn("snu:dl:m4a", data)

    def test_menu_and_study(self):
        menu = suno_menu()
        data = [b["callback_data"]
                for row in menu["reply_markup"]["inline_keyboard"] for b in row]
        self.assertIn("snu:link", data)
        self.assertIn("snu:study", data)
        study = suno_study()
        self.assertIn("Mango", study["text"])
        self.assertIn("AES", study["text"])


class RouterSunoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import os
        from session_manager import SessionManager
        self.temp = TemporaryDirectory()
        self.store = SessionManager(Path(self.temp.name) / "sessions.db")
        self.env = mock.patch.dict(os.environ, {
            "TELEGRAM_ALLOWED_USER_IDS": "12345",
            "TELEGRAM_BOT_TOKEN": "123:TEST",
            "MINDA_API_KEY": "",
            "MINDA_BASE_URL": "",
        })
        self.env.start()
        self.agent = MagicMock()
        self.agent.record_search.side_effect = lambda *a, **k: (10, 1)
        self.agent.summary_text.side_effect = lambda: "agent test"
        self.agent_patch = mock.patch("bot_router.agent_skills",
                                      return_value=self.agent)
        self.agent_patch.start()

    async def asyncTearDown(self):
        self.agent_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def update_msg(self, text):
        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query = None
        update.message.text = text
        update.message.reply_text = AsyncMock()
        return update

    def update_cb(self, data, with_message=False):
        update = MagicMock()
        update.effective_user.id = 12345
        cb = MagicMock()
        cb.data = data
        cb.answer = AsyncMock()
        cb.edit_message_text = AsyncMock()
        update.callback_query = cb
        if with_message:
            update.message = MagicMock()
            update.message.reply_text = AsyncMock()
        else:
            update.message = None
        return update

    async def test_command_shows_menu(self):
        from bot_router import handle_update
        update = self.update_msg("/suno")
        with mock.patch("bot_router.suno_menu",
                        return_value={"text": "MENU",
                                      "reply_markup": {"inline_keyboard": []}}):
            await handle_update(update, MagicMock(), store=self.store)
        update.message.reply_text.assert_awaited_once()
        self.assertEqual(update.message.reply_text.await_args.args[0], "MENU")

    async def test_callback_menu(self):
        from bot_router import handle_update
        update = self.update_cb("snu:menu")
        with mock.patch("bot_router.suno_menu",
                        return_value={"text": "MENU",
                                      "reply_markup": {"inline_keyboard": []}}):
            await handle_update(update, MagicMock(), store=self.store)
        update.callback_query.edit_message_text.assert_awaited()
        self.assertEqual(
            update.callback_query.edit_message_text.await_args.args[0], "MENU")

    async def test_callback_study(self):
        from bot_router import handle_update
        update = self.update_cb("snu:study")
        await handle_update(update, MagicMock(), store=self.store)
        self.assertEqual(
            update.callback_query.edit_message_text.await_args.args[0],
            suno_study()["text"])

    async def test_callback_link_prompt(self):
        from bot_router import handle_update
        update = self.update_cb("snu:link")
        await handle_update(update, MagicMock(), store=self.store)
        state, _ = self.store.get_session(12345)
        self.assertEqual(state, "SONG_LINK")

    async def test_typed_link_triggers_flow(self):
        from bot_router import handle_update
        info = make_schema(CID)
        update = self.update_msg("https://suno.com/s/" + CID[:16])
        with mock.patch("bot_router.fetch_song_info",
                        return_value=_clean_info(info)) as fs, \
             mock.patch("bot_router.song_card",
                        return_value={"text": "CARD",
                                      "reply_markup": {"inline_keyboard": []}}):
            await handle_update(update, MagicMock(), store=self.store)
        fs.assert_called_once()
        state, sdata = self.store.get_session(12345)
        self.assertEqual(state, "SONG_LINK")
        self.assertEqual(sdata["info"]["title"], "Test Song")
        # the card was delivered
        self.assertTrue(any(call.args and call.args[0] == "CARD"
                            for call in update.message.reply_text.await_args_list))

    async def test_song_link_state_non_link_rejected(self):
        from bot_router import handle_update
        self.store.set_session(12345, "SONG_LINK", {})
        update = self.update_msg("hello world")
        with mock.patch("bot_router.fetch_song_info") as fs:
            await handle_update(update, MagicMock(), store=self.store)
        fs.assert_not_called()
        update.message.reply_text.assert_awaited_once()
        self.assertIn("not a Suno link",
                      update.message.reply_text.await_args.args[0])

    async def test_song_link_state_link_processed(self):
        from bot_router import handle_update
        info = make_schema(CID)
        self.store.set_session(12345, "SONG_LINK", {})
        update = self.update_msg("https://suno.com/s/" + CID[:16])
        with mock.patch("bot_router.fetch_song_info",
                        return_value=_clean_info(info)), \
             mock.patch("bot_router.song_card",
                        return_value={"text": "CARD",
                                      "reply_markup": {"inline_keyboard": []}}):
            await handle_update(update, MagicMock(), store=self.store)
        state, sdata = self.store.get_session(12345)
        self.assertEqual(state, "SONG_LINK")
        self.assertEqual(sdata["info"]["title"], "Test Song")

    async def test_dl_callback_sends_audio(self):
        from bot_router import handle_update
        info = _clean_info(make_schema(CID))
        self.store.set_session(12345, "SONG_LINK", {"info": info,
                                                    "url": "https://suno.com/song/" + CID})
        update = self.update_cb("snu:dl:m4a", with_message=True)
        with mock.patch("bot_router.deliver_song",
                        return_value={"size": 1_000_000, "via": "api",
                                      "filename": "a.m4a"}) as ds:
            await handle_update(update, MagicMock(), store=self.store)
        ds.assert_called_once()
        # success confirmation sent
        self.assertTrue(any("as M4A" in str(c.args)
                            for c in update.message.reply_text.await_args_list))

    async def test_dl_callback_fallback_when_service_down(self):
        from bot_router import handle_update
        info = _clean_info(make_schema(CID))
        self.store.set_session(12345, "SONG_LINK", {"info": info,
                                                    "url": "https://suno.com/song/" + CID})
        update = self.update_cb("snu:dl:m4a", with_message=True)
        with mock.patch("bot_router.deliver_song",
                        side_effect=ValueError("decrypt down")), \
             mock.patch("bot_router.link_only_card",
                        return_value={"text": "FALLBACK",
                                      "reply_markup": {"inline_keyboard": []}}):
            await handle_update(update, MagicMock(), store=self.store)
        # the callback message is edited to the fallback card
        self.assertEqual(
            update.callback_query.edit_message_text.await_args.args[0], "FALLBACK")


def _clean_info(info):
    """fetch_song_info returns the module's dict shape; make sure it has all keys."""
    out = {
        "content_id": info.get("id", CID),
        "title": info.get("title", "Test Song"),
        "artist": info.get("display_name", "An Artist"),
        "handle": info.get("handle", "anartist"),
        "style": info.get("metadata", {}).get("tags", ""),
        "duration": float(info.get("metadata", {}).get("duration", 0)),
        "model": info.get("model_name", ""),
        "status": info.get("status", "complete"),
        "cover_url": info.get("image_large_url", ""),
        "media_url": (info.get("media_urls") or [{}])[0].get("url"),
        "share_url": "https://suno.com/song/" + info.get("id", CID),
    }
    return out


if __name__ == "__main__":
    unittest.main()
