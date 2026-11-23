import unittest
from unittest import mock
from unittest.mock import MagicMock

import mql5_scout
from mql5_scout import (INDEX_RE, mql5_item_by_index, mql5_listing_keyboard,
                        mql5_paged_message, parse_tiles, resolve_file,
                        scrape_trending)

SAMPLE_HTML = """
<div class="title"> <a href="/en/code/78579" title="Prop Firm Guard - daily loss protection">Prop Firm Guard</a> </div>
<div class="title"> <a href="/en/code/78581" title="GDS Renko &#x2B; RSI Demo EA">GDS Renko + RSI</a> </div>
<div class="title"> <a href="/en/code/ab12" title="bad id">Bad</a> </div>
<div class="title"> <a href="/en/code/12" title="short id">Short</a> </div>
"""
ITEMS = [{"id": "78579", "title": "Prop Firm Guard",
          "url": "https://www.mql5.com/en/code/78579"},
         {"id": "78581", "title": "GDS Renko + RSI",
          "url": "https://www.mql5.com/en/code/78581"}]


class ParseTilesTests(unittest.TestCase):
    def test_parses_valid_items(self):
        out = parse_tiles(SAMPLE_HTML)
        self.assertEqual(out, [("78579", "Prop Firm Guard - daily loss protection"),
                               ("78581", "GDS Renko + RSI Demo EA")])

    def test_empty_html(self):
        self.assertEqual(parse_tiles(""), [])
        self.assertEqual(parse_tiles(None), [])


class ScrapeTrendingTests(unittest.TestCase):
    def _client(self, text):
        client = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.text = text
        client.get = MagicMock(return_value=response)
        return client

    def test_returns_items(self):
        items = scrape_trending("mt5", "experts", client=self._client(SAMPLE_HTML))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["id"], "78579")
        self.assertEqual(items[0]["url"], "https://www.mql5.com/en/code/78579")

    def test_no_tiles_raises(self):
        with self.assertRaises(ValueError):
            scrape_trending("mt5", "experts", client=self._client("<html></html>"))


class ResolveFileTests(unittest.TestCase):
    def test_prefers_direct_source_file(self):
        client = MagicMock()
        client.get = MagicMock(return_value=MagicMock(
            raise_for_status=MagicMock(),
            text='<a href="/en/code/download/78579/PropFirmGuard.mq5">Download</a>'))
        info = resolve_file("78579", client=client)
        self.assertEqual(info["url"], "https://www.mql5.com/en/code/download/78579/PropFirmGuard.mq5")
        self.assertEqual(info["filename"], "PropFirmGuard.mq5")
        self.assertEqual(info["kind"], "source")

    def test_falls_back_to_zip(self):
        client = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.text = "<html>no file link</html>"
        response.status_code = 200
        client.get = MagicMock(return_value=response)
        info = resolve_file("78579", client=client)
        self.assertEqual(info["url"], "https://www.mql5.com/en/code/download/78579.zip")
        self.assertEqual(info["kind"], "zip")

    def test_nothing_found_raises(self):
        class Resp:
            def __init__(self, ok):
                self.ok = ok
            def raise_for_status(self):
                if not self.ok:
                    raise ValueError("http 404")
            @property
            def text(self):
                return "<html>none</html>"
            status_code = 404
        client = MagicMock()
        client.get = MagicMock(side_effect=[Resp(True), Resp(False)])
        with self.assertRaises(ValueError):
            resolve_file("78579", client=client)


class PagingTests(unittest.TestCase):
    def test_keyboard_shape_and_limits(self):
        many = [{"id": str(1000 + i), "title": "EA " + str(i),
                 "url": "https://x"} for i in range(10)]
        kb = mql5_listing_keyboard(many, 0)
        rows = kb["inline_keyboard"]
        # 3 item rows, then a nav row, then home
        self.assertEqual(rows[0][0]["callback_data"], "dlm:0")
        self.assertEqual(rows[1][0]["callback_data"], "dlm:1")
        self.assertEqual(rows[2][0]["callback_data"], "dlm:2")
        nav = rows[3]
        # 10 items -> 4 pages, so page 0 has a Next button but no Prev
        self.assertTrue(any(r["callback_data"] == "mql5s:1" for r in nav))
        self.assertFalse(any(r["callback_data"] == "mql5s:-1" for r in nav))
        # home row last
        self.assertEqual(rows[-1][0]["callback_data"], "ui:home")

    def test_page_out_of_range(self):
        with self.assertRaises(ValueError):
            mql5_listing_keyboard(ITEMS, 5)

    def test_paged_message_text_and_markup(self):
        msg = mql5_paged_message(ITEMS, 0)
        self.assertIn("MQL5 trending", msg["text"])
        self.assertIn("1. Prop Firm Guard", msg["text"])
        self.assertIn("inline_keyboard", msg["reply_markup"])

    def test_item_by_index(self):
        self.assertEqual(mql5_item_by_index(ITEMS, "1")["id"], "78581")
        self.assertEqual(mql5_item_by_index(ITEMS, "0")["id"], "78579")

    def test_item_by_index_rejects_bad(self):
        for bad in ("", "x", "-1", "5"):
            with self.assertRaises(ValueError):
                mql5_item_by_index(ITEMS, bad)


class DeliverFileTests(unittest.TestCase):
    def test_delivers_source_file(self):
        item = dict(ITEMS[0])
        payload = b"//+\n//+" + b"-" * 300  # >256 bytes, MQL source
        session = MagicMock()
        session.get = MagicMock(return_value=MagicMock(
            raise_for_status=MagicMock(),
            iter_content=lambda n: iter([payload]),
            close=MagicMock()))
        with mock.patch.object(mql5_scout, "resolve_file",
                               return_value={"url": "https://x", "filename": "A.mq5",
                                              "kind": "source"}), \
             mock.patch("agent.send") as snd:
            kind, url, size = mql5_scout.deliver_file("123:T", "456", item, session=session)
        self.assertEqual(kind, "source")
        self.assertEqual(size, len(payload))
        snd.assert_called_once()
        # agent.send(session, token, chat_id, name, data, caption)
        self.assertEqual(snd.call_args.args[0], session)
        self.assertEqual(snd.call_args.args[1], "123:T")
        self.assertEqual(snd.call_args.args[2], "456")
        self.assertEqual(snd.call_args.args[3], "A.mq5")

    def test_invalid_id_raises(self):
        with self.assertRaises(ValueError):
            mql5_scout.deliver_file("123:T", "456", {"id": "bad!"}, session=MagicMock())


if __name__ == "__main__":
    unittest.main()
