import unittest
from unittest import mock
from unittest.mock import MagicMock

import ex4_scout
from ex4_scout import (ex4_fetch_listing, ex4_item_by_index,
                       ex4_item_detail, ex4_listing_message, ex4_menu,
                       ex4_study, parse_channel_posts, parse_site_catalog)

# Realistic channel preview HTML (t.me/s/<channel>): newest first; each EA =
# a file post (document) immediately followed by its description post. The
# pinned post has no document. (Order matches the live page.)
CHANNEL_HTML = """
<div data-post="ex4tomq4decompilercom/457">
  <a class="tgme_widget_message_document_wrap" href="https://t.me/ex4tomq4decompilercom/457">
    <div class="tgme_widget_message_document_title accent_color" dir="auto">Dual Striker PRO MT4.ex4</div>
    <div class="tgme_widget_message_document_extra" dir="auto">59.5 KB</div>
  </a>
  <div class="tgme_widget_message_text js-message_text" dir="auto">Dual Striker PRO MT4 \U0001F4B0 Decompiled</div>
</div>
<div data-post="ex4tomq4decompilercom/456">
  <div class="tgme_widget_message_text js-message_text" dir="auto">Dual Striker PRO MT4 \U0001F4B0 Decompiled. Dual Striker uses a momentum-based strategy for trading Gold (XAUUSD). No martingale, no grid.</div>
</div>
<div data-post="ex4tomq4decompilercom/455">
  <div class="tgme_widget_message_text js-message_text" dir="auto">EX4 TO MQ4 DECOMPILER COM pinned a file</div>
</div>
<div data-post="ex4tomq4decompilercom/454">
  <a class="tgme_widget_message_document_wrap" href="https://t.me/ex4tomq4decompilercom/454">
    <div class="tgme_widget_message_document_title accent_color" dir="auto">Apex Carry Edge.ex4</div>
    <div class="tgme_widget_message_document_extra" dir="auto">82.1 KB</div>
  </a>
  <div class="tgme_widget_message_text js-message_text" dir="auto">Apex Carry Edge \U0001F4B0 Decompiled</div>
</div>
"""

# Realistic site catalogue HTML: JSON-LD ItemList + product cards.
SITE_HTML = """
<script type="application/ld+json">
{"@type":"ItemList","name":"Free MT4 Forex Trading Robots","itemListElement":[
  {"@type":"ListItem","position":1,"name":"Solo Sniper Pro mw"},
  {"@type":"ListItem","position":2,"name":"Flexible EA"},
  {"@type":"ListItem","position":3,"name":"Dual Striker PRO MT4"}
]}
</script>
<article class="product-card" id="product-01-solo-sniper-pro-mw">
  <span class="product-type">MT4 EXPERT ADVISOR</span>
  <h2 class="product-title" itemprop="name">Solo Sniper Pro mw Decompiled \U0001F4B0</h2>
  <p class="product-seo-description">Solo Sniper Pro mw is a powerful scalping EA for MT4. High win rate, M15.</p>
  <a class="product-button" href="https://t.me/ex4tomq4decompilercom/471">Download EX4</a>
</article>
<article class="product-card" id="product-02-flexible-ea">
  <span class="product-type">MT4 EXPERT ADVISOR</span>
  <h2 class="product-title" itemprop="name">Flexible EA Decompiled \U0001F4B0</h2>
  <p class="product-seo-description">Flexible EA loads your custom indicators to trigger signals. Grid, averaging, trailing.</p>
  <a class="product-button" href="https://t.me/ex4tomq4decompilercom/469">Download EX4</a>
</article>
<article class="product-card" id="product-03-dual-striker-pro-mt4">
  <span class="product-type">MT4 EXPERT ADVISOR</span>
  <h2 class="product-title" itemprop="name">Dual Striker PRO MT4 Decompiled \U0001F4B0</h2>
  <p class="product-seo-description">Dual Striker uses a momentum-based strategy for trading Gold (XAUUSD).</p>
  <a class="product-button" href="https://t.me/ex4tomq4decompilercom/457">Download EX4</a>
</article>
"""


def _client(text):
    client = MagicMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = text
    client.get = MagicMock(return_value=resp)
    return client


class ParseChannelTests(unittest.TestCase):
    def test_parses_doc_and_desc_posts(self):
        posts = parse_channel_posts(CHANNEL_HTML)
        # doc posts carry filename+size
        self.assertEqual(posts[454]["filename"], "Apex Carry Edge.ex4")
        self.assertEqual(posts[454]["size"], "82.1 KB")
        self.assertEqual(posts[457]["filename"], "Dual Striker PRO MT4.ex4")
        # the paired description post (456) is folded into the doc post
        self.assertIn("momentum-based strategy", posts[457].get("desc", ""))
        # pinned post (455) -> no document
        self.assertNotIn("filename", posts.get(455, {}))

    def test_empty_html(self):
        self.assertEqual(parse_channel_posts(""), {})
        self.assertEqual(parse_channel_posts(None), {})


class ParseSiteTests(unittest.TestCase):
    def test_parses_catalogue(self):
        names, cards = parse_site_catalog(SITE_HTML)
        self.assertEqual(names, ["Solo Sniper Pro mw", "Flexible EA",
                                 "Dual Striker PRO MT4"])
        self.assertIn("dual striker pro mt4", cards)
        card = cards["dual striker pro mt4"]
        self.assertEqual(card["name"], "Dual Striker PRO MT4")
        self.assertEqual(card["post"], "457")
        self.assertIn("t.me/ex4tomq4decompilercom/457", card["file_url"])
        self.assertIn("momentum-based strategy", card["desc"])

    def test_empty(self):
        names, cards = parse_site_catalog("")
        self.assertEqual(names, [])
        self.assertEqual(cards, {})


class FetchListingTests(unittest.TestCase):
    def test_recent_returns_docs_newest_first(self):
        items = ex4_fetch_listing("recent", client=_client(CHANNEL_HTML))
        self.assertTrue(all(it["recent"] for it in items))
        # newest doc first (457 > 454)
        self.assertEqual(items[0]["name"], "Dual Striker PRO MT4")
        self.assertEqual(items[0]["filename"], "Dual Striker PRO MT4.ex4")
        self.assertIn("457", items[0]["url"])

    def test_full_merges_catalogue_with_recent(self):
        # full needs BOTH channel + catalogue: two get() calls in order
        client = MagicMock()
        r1 = MagicMock(); r1.raise_for_status = MagicMock(); r1.text = CHANNEL_HTML
        r2 = MagicMock(); r2.raise_for_status = MagicMock(); r2.text = SITE_HTML
        client.get = MagicMock(side_effect=[r1, r2])
        items = ex4_fetch_listing("full", client=client)
        by_name = {it["name"]: it for it in items}
        # all catalogue EAs present
        for n in ("Solo Sniper Pro mw", "Flexible EA", "Dual Striker PRO MT4"):
            self.assertIn(n, by_name)
        # Dual Striker is also a live doc post -> flagged recent, size present
        ds = by_name["Dual Striker PRO MT4"]
        self.assertTrue(ds["recent"])
        self.assertEqual(ds["size"], "59.5 KB")
        # recent items float to the top
        self.assertTrue(items[0]["recent"])

    def test_full_channel_down_falls_back_to_catalogue_only(self):
        # channel raises -> fetch_listing should still work from catalogue?
        # (current design: scrape_channel first; make it resilient)
        items = ex4_fetch_listing("full", client=_client(SITE_HTML))
        # at minimum catalogue names present (channel empty is OK)
        self.assertTrue(items)

    def test_ind_returns_curated_indicators_newest_first(self):
        # channel down is non-fatal for the pinned indicator list
        items = ex4_fetch_listing("ind", client=_client(""))
        self.assertEqual(len(items), len(ex4_scout.INDICATORS))
        self.assertTrue(all(it["type"] == "MT4 INDICATOR" for it in items))
        posts = [int(it["post"]) for it in items]
        self.assertEqual(posts, sorted(posts, reverse=True))
        by_post = {it["post"]: it for it in items}
        # Wolf Wave is the .mq4 source drop
        ww = by_post["232"]
        self.assertEqual(ww["filename"], "Wolf Wave MT4.mq4")
        self.assertEqual(ww["url"], "https://t.me/ex4tomq4decompilercom/232")
        # every indicator carries a mechanism note, not just marketing
        self.assertTrue(all(it["desc"] for it in items))

    def test_ind_enriched_when_recent_preview_has_it(self):
        # Multi Sniper (post 465) is in the /s/ preview -> recent flag + size
        html = '<div data-post="ex4tomq4decompilercom/465">\n' \
               '  <div class="tgme_widget_message_document_title accent_color" dir="auto">Multi Sniper mq.ex4</div>\n' \
               '  <div class="tgme_widget_message_document_extra" dir="auto">91.5 KB</div>\n' \
               '</div>'
        items = ex4_fetch_listing("ind", client=_client(html))
        ms = [it for it in items if it["post"] == "465"][0]
        self.assertTrue(ms["recent"])
        self.assertEqual(ms["size"], "91.5 KB")
        self.assertEqual(ms["filename"], "Multi Sniper mq.ex4")


class PagingTests(unittest.TestCase):
    ITEMS = [{"name": "EA %d" % i, "type": "MT4 EXPERT ADVISOR",
              "recent": i < 2, "filename": ("EA%d.ex4" % i if i < 2 else ""),
              "size": ("10 KB" if i < 2 else ""),
              "desc": "d", "url": "https://t.me/ex4tomq4decompilercom/%d" % i,
              "post": str(i)} for i in range(7)]

    def test_listing_message_text_and_markup(self):
        msg = ex4_listing_message(self.ITEMS, 0, "full")
        self.assertIn("1. EA 0", msg["text"])
        self.assertIn("recent", msg["text"])
        self.assertIn("inline_keyboard", msg["reply_markup"])
        rows = msg["reply_markup"]["inline_keyboard"]
        self.assertEqual(rows[0][0]["callback_data"], "ex4i:0")

    def test_nav_appears_with_multiple_pages(self):
        msg = ex4_listing_message(self.ITEMS, 0, "full")
        rows = msg["reply_markup"]["inline_keyboard"]
        self.assertTrue(any(r["callback_data"] == "ex4p:1" for r in rows[-1]))
        self.assertFalse(any(r["callback_data"] == "ex4p:-1" for r in rows[-1]))
        self.assertEqual(rows[-1][-1]["callback_data"], "ui:home")

    def test_item_by_index(self):
        self.assertEqual(ex4_item_by_index(self.ITEMS, "3")["name"], "EA 3")
        for bad in ("", "x", "-1", "99"):
            with self.assertRaises(ValueError):
                ex4_item_by_index(self.ITEMS, bad)


class MenuTests(unittest.TestCase):
    def test_menu_shape(self):
        menu = ex4_menu()
        self.assertIn("EX4", menu["text"])
        cds = [b["callback_data"] for row in menu["reply_markup"]["inline_keyboard"]
               for b in row]
        self.assertIn("ex4:recent", cds)
        self.assertIn("ex4:full", cds)
        self.assertIn("ex4:study", cds)
        self.assertIn("ui:home", cds)

    def test_study_text_mentions_method(self):
        menu = ex4_study()
        self.assertIn("decompil", menu["text"].lower())
        self.assertIn("tg://", menu["text"])


class ItemDetailTests(unittest.TestCase):
    def test_detail_fetches_paired_desc(self):
        client = _client("")
        item = {"name": "Dual Striker PRO MT4", "type": "MT4 EXPERT ADVISOR",
                "recent": True, "filename": "Dual Striker PRO MT4.ex4",
                "size": "59.5 KB",
                "desc": "Dual Striker PRO MT4 \U0001F4B0 Decompiled",
                "url": "https://t.me/ex4tomq4decompilercom/457",
                "post": "457"}
        # detail scans the +/-2 window around the file post (457)
        with mock.patch.object(ex4_scout, "_fetch_desc",
                               return_value="Dual Striker uses a momentum-based "
                                            "strategy for trading Gold. No grid.") as fd:
            text, kb = ex4_item_detail(item, client=client)
        self.assertEqual([c.args[0] for c in fd.call_args_list],
                         [456, 458, 455, 459])
        self.assertIn("Dual Striker uses a momentum-based strategy", text)
        self.assertIn("59.5 KB", text)
        self.assertIn("\U0001F4E5 Get it on Telegram", str(kb))
        # keyboard: url button + back/home
        btns = kb["inline_keyboard"][0][0]
        self.assertEqual(btns["url"], "https://t.me/ex4tomq4decompilercom/457")

    def test_detail_neighbour_desc_rejected_by_name_guard(self):
        # the neighbour's description mentions a DIFFERENT product: it must
        # not be adopted even though it is longer
        item = {"name": "Flexible EA", "type": "MT4 EXPERT ADVISOR",
                "recent": False, "filename": "", "size": "",
                "desc": "Flexible EA loads your custom indicators to trigger signals.",
                "url": "https://t.me/ex4tomq4decompilercom/469", "post": "469"}
        with mock.patch.object(ex4_scout, "_fetch_desc",
                               return_value="Solo Sniper Pro is a scalping robot "
                                            "with compound risk management and a "
                                            "high win rate on M15."):
            text, kb = ex4_item_detail(item, client=_client(""))
        self.assertIn("Flexible EA loads your custom indicators", text)
        self.assertNotIn("Solo Sniper Pro", text)

    def test_detail_long_desc_truncated(self):
        item = {"name": "X", "type": "MT4 EXPERT ADVISOR", "recent": True,
                "filename": "X.ex4", "size": "",
                "desc": "short", "url": "https://t.me/x/10", "post": "10"}
        with mock.patch.object(ex4_scout, "_fetch_desc",
                               return_value="w" * 900):
            text, kb = ex4_item_detail(item, client=_client(""))
        # truncated to MAX_DESC + ellipsis
        self.assertIn("\u2026", text)
        self.assertLessEqual(len(text), 1400)

    def test_detail_fetch_failure_falls_back(self):
        item = {"name": "X", "type": "MT4 EXPERT ADVISOR", "recent": True,
                "filename": "X.ex4", "size": "",
                "desc": "catalogue blurb stays", "url": "https://t.me/x/10",
                "post": "10"}
        with mock.patch.object(ex4_scout, "_fetch_desc",
                               side_effect=ValueError("net")):
            text, kb = ex4_item_detail(item, client=_client(""))
        self.assertIn("catalogue blurb stays", text)


if __name__ == "__main__":
    unittest.main()
