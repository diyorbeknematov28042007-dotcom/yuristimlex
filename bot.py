"""
Lex.uz Telegram Bot
Inline mode orqali O'zbekiston qonunchiligini qidirish va DOCX yuklab olish.
Render.com ga deploy qilish uchun moslashtirilgan (webhook mode).
"""

import asyncio
import logging
import os
import re
from typing import Optional

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════
#  MUHIT O'ZGARUVCHILARI (Environment Variables)
# ═══════════════════════════════════════════════════════
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")   # https://SIZNING-APP.onrender.com
PORT        = int(os.getenv("PORT", 8080))
WEBHOOK_PATH = "/webhook"

# ═══════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("lexuz_bot")

# ═══════════════════════════════════════════════════════
#  KONSTANTALAR
# ═══════════════════════════════════════════════════════
BASE_URL   = "https://lex.uz"
SEARCH_URL = f"{BASE_URL}/uz/search/bybody"
SUGGEST_URL = f"{BASE_URL}/uz/suggestions/act_title"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uz-UZ,uz;q=0.9,ru;q=0.7,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://lex.uz/",
}

STATUS_EMOJI = {"Y": "✅", "R": "❌", "N": "⚠️"}
STATUS_LABEL = {"Y": "Amaldagi", "R": "Kuchini yo'qotgan", "N": "Amalda emas"}

DOC_TYPE_EMOJI = {
    "Konstitutsiya": "📜",
    "Kodeks":        "📚",
    "Qonun":         "⚖️",
    "Farmon":        "📋",
    "Qaror":         "📄",
    "Buyruq":        "📝",
}

# ═══════════════════════════════════════════════════════
#  LEX.UZ SCRAPER SINFI
# ═══════════════════════════════════════════════════════
class LexuzScraper:
    """Lex.uz saytidan ma'lumot oluvchi klass."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            connector = aiohttp.TCPConnector(ssl=False, limit=10)
            self._session = aiohttp.ClientSession(
                headers=REQUEST_HEADERS,
                timeout=timeout,
                connector=connector,
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ─── QIDIRUV ──────────────────────────────────────
    async def search(self, query: str, page: int = 0) -> list[dict]:
        """Lex.uz dan hujjatlarni qidirish. Lotin o'zbek (lang=4) asosiy."""
        session = await self.get_session()
        results = []

        # Lotin o'zbek (lang=4) va kiril (lang=3) da qidirish
        for lang in [4, 3]:
            try:
                params = {"query": query, "page": page, "lang": lang}
                async with session.get(SEARCH_URL, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(f"Search {lang}: HTTP {resp.status}")
                        continue
                    html = await resp.text(encoding="utf-8", errors="replace")

                found = self._parse_search_html(html)
                # ID lari takrorlanmasin
                existing_ids = {r["id"] for r in results}
                for doc in found:
                    if doc["id"] not in existing_ids:
                        results.append(doc)
                        existing_ids.add(doc["id"])

                if len(results) >= 10:
                    break

            except asyncio.TimeoutError:
                logger.warning(f"Search timeout (lang={lang})")
            except Exception as e:
                logger.error(f"Search error (lang={lang}): {e}")

        return results[:10]

    def _parse_search_html(self, html: str) -> list[dict]:
        """Search natijalar HTML sini tahlil qilish."""
        soup = BeautifulSoup(html, "lxml")
        results = []

        # ── Usul 1: .actCard sinfi (asosiy natija kartochkasi) ──
        cards = soup.select(".actCard, .act-card, .search-result__item")
        if cards:
            for card in cards:
                doc = self._parse_card(card)
                if doc:
                    results.append(doc)
            return results

        # ── Usul 2: /docs/ havolalarini to'g'ridan-to'g'ri topish ──
        seen_ids = set()
        for link in soup.select("a[href*='/docs/']"):
            href = link.get("href", "")
            m = re.search(r"/docs/(-?\d+)", href)
            if not m:
                continue
            doc_id = m.group(1)
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)

            title = link.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            # Atrofdagi matndan qo'shimcha ma'lumot
            parent = link.find_parent(["div", "li", "tr"]) or link
            parent_text = parent.get_text(" ", strip=True)

            doc = {
                "id":     doc_id,
                "title":  title[:200],
                "date":   self._extract_date(parent_text),
                "num":    self._extract_num(parent_text),
                "status": self._extract_status(parent_text),
                "type":   self._extract_type(title),
                "url":    f"{BASE_URL}/docs/{doc_id}",
            }
            results.append(doc)

        return results

    def _parse_card(self, card) -> Optional[dict]:
        """actCard elementidan hujjat ma'lumotlarini ajratish."""
        try:
            link = card.select_one("a[href*='/docs/']")
            if not link:
                return None
            href = link.get("href", "")
            m = re.search(r"/docs/(-?\d+)", href)
            if not m:
                return None

            doc_id = m.group(1)
            title  = link.get_text(strip=True) or card.get_text(strip=True)[:100]
            full   = card.get_text(" ", strip=True)

            # Status class dan: actCard__status--Y / --R / --N
            status = "Y"
            status_el = card.select_one("[class*='status--']")
            if status_el:
                cls = " ".join(status_el.get("class", []))
                for s in ["Y", "R", "N"]:
                    if f"--{s}" in cls:
                        status = s
                        break

            return {
                "id":     doc_id,
                "title":  title[:200],
                "date":   self._extract_date(full),
                "num":    self._extract_num(full),
                "status": status,
                "type":   self._extract_type(title),
                "url":    f"{BASE_URL}/docs/{doc_id}",
            }
        except Exception:
            return None

    # ─── HUJJAT MA'LUMOTLARI ──────────────────────────
    async def get_doc_info(self, doc_id: str) -> Optional[dict]:
        """Hujjat sahifasidan to'liq ma'lumot olish."""
        session = await self.get_session()
        url = f"{BASE_URL}/docs/{doc_id}"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.error(f"get_doc_info {doc_id}: {e}")
            return None

        return self._parse_doc_page(html, doc_id)

    def _parse_doc_page(self, html: str, doc_id: str) -> dict:
        """Hujjat sahifasini tahlil qilish."""
        soup = BeautifulSoup(html, "lxml")

        # Sarlavha - page title dan
        page_title = soup.find("title")
        title = page_title.get_text(strip=True) if page_title else f"Hujjat #{doc_id}"
        # "LEX.UZ - " prefiksini olib tashlash
        title = re.sub(r"^.*?LEX\.UZ\s*[-–]\s*", "", title, flags=re.I).strip()

        # docHeader__item-label — tur + raqam (masalan: "O'RQ-682-son 20.04.2021")
        label_el = soup.select_one(".docHeader__item-label")
        label    = label_el.get_text(strip=True) if label_el else ""

        full_text = soup.get_text(" ", strip=True)

        # Sana - labeldan yoki to'liq matndan
        date = self._extract_date(label) or self._extract_date(full_text)

        # Hujjat raqami
        num = self._extract_num(label) or self._extract_num(full_text)

        # Holat
        status = "Y"
        low = full_text.lower()
        if "kuchini yo'qotgan" in low or "утратил силу" in low:
            status = "R"
        elif "amalda emas" in low:
            status = "N"

        # Tur
        doc_type = self._extract_type(title + " " + label)

        return {
            "id":     doc_id,
            "title":  title,
            "label":  label,
            "date":   date,
            "num":    num,
            "status": status,
            "type":   doc_type,
            "url":    f"{BASE_URL}/docs/{doc_id}",
        }

    # ─── DOCX YUKLAB OLISH ────────────────────────────
    async def download_docx(self, doc_id: str) -> Optional[bytes]:
        """
        Hujjatni DOCX formatda yuklab olish.
        Lex.uz rasmiy download URLlarini ketma-ket sinab ko'radi.
        """
        session = await self.get_session()

        # Lex.uz download endpointlari (aniqlanganidan tashqarigacha)
        candidates = [
            f"{BASE_URL}/uz/getfile?id={doc_id}",
            f"{BASE_URL}/uz/getfile?id={doc_id}&type=docx",
            f"{BASE_URL}/getfile?id={doc_id}",
            f"{BASE_URL}/docx/{doc_id}",
            f"{BASE_URL}/uz/docfile/{doc_id}",
        ]

        for url in candidates:
            try:
                async with session.get(url, allow_redirects=True) as resp:
                    ct = resp.headers.get("Content-Type", "").lower()
                    logger.debug(f"Download try: {url} → {resp.status} | {ct}")

                    if resp.status != 200:
                        continue

                    is_docx = (
                        "officedocument" in ct
                        or "octet-stream" in ct
                        or "msword" in ct
                        or ct == "application/docx"
                    )
                    if not is_docx:
                        # Content-Disposition ni tekshirish
                        cd = resp.headers.get("Content-Disposition", "")
                        if ".doc" not in cd.lower():
                            continue

                    data = await resp.read()
                    # DOCX magic bytes: PK\x03\x04
                    if len(data) > 4 and data[:2] == b"PK":
                        logger.info(f"DOCX downloaded from {url}, size={len(data)}")
                        return data

            except Exception as e:
                logger.debug(f"Download error {url}: {e}")

        return None

    # ─── YORDAMCHI METODLAR ───────────────────────────
    @staticmethod
    def _extract_date(text: str) -> str:
        m = re.search(r"\b(\d{2}\.\d{2}\.\d{4})\b", text)
        return m.group(1) if m else ""

    @staticmethod
    def _extract_num(text: str) -> str:
        # O'RQ-682-son, PQ-2761, ORQ-613, №613 va hokazo
        # 1) Harf-raqam kombinatsiyali raqam: O'RQ-682, PQ-2761
        m = re.search(
            r"[A-ZА-ЯЎҲҚa-zа-яўҳқ']{1,6}-\d+(?:-[a-zA-Z]+)?",
            text,
        )
        if m:
            return m.group(0).strip()
        # 2) Faqat raqamli №-sonli: №613 yoki № 613
        m2 = re.search(r"№\s*(\d+)", text)
        if m2:
            return f"№{m2.group(1)}"
        return ""

    @staticmethod
    def _extract_status(text: str) -> str:
        low = text.lower()
        if "kuchini yo'qotgan" in low or "утратил" in low:
            return "R"
        if "amalda emas" in low:
            return "N"
        return "Y"

    @staticmethod
    def _extract_type(text: str) -> str:
        for t in DOC_TYPE_EMOJI:
            if t.lower() in text.lower():
                return t
        return "Hujjat"


# ═══════════════════════════════════════════════════════
#  YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════
scraper = LexuzScraper()


def doc_card_text(doc: dict) -> str:
    """Hujjat kartochkasi matni."""
    s_emoji = STATUS_EMOJI.get(doc.get("status", "Y"), "❓")
    s_label = STATUS_LABEL.get(doc.get("status", "Y"), "")
    d_emoji = DOC_TYPE_EMOJI.get(doc.get("type", ""), "📄")
    date    = doc.get("date", "")
    num     = doc.get("num", "")

    lines = [f"{d_emoji} <b>{doc['title']}</b>\n"]
    lines.append(f"{s_emoji} <b>Holat:</b> {s_label}")
    if date:
        lines.append(f"📅 <b>Sana:</b> {date}")
    if num:
        lines.append(f"🔖 <b>Raqami:</b> {num}")
    lines.append(f"\n🔗 <a href='{doc['url']}'>Lex.uz da ko'rish</a>")
    return "\n".join(lines)


def doc_action_keyboard(doc_id: str) -> InlineKeyboardMarkup:
    """Hujjat amallar klaviaturasi."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📥 DOCX yuklab olish",
                callback_data=f"dl:{doc_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🌐 Lex.uz da ochish",
                url=f"{BASE_URL}/docs/{doc_id}",
            ),
        ],
    ])


# ═══════════════════════════════════════════════════════
#  BOT VA DISPATCHER
# ═══════════════════════════════════════════════════════
bot = Bot(token=BOT_TOKEN, default=None)  # ParseMode har so'rovda beriladi
dp  = Dispatcher()


# ─── /start ───────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: Message):
    text = (
        "⚖️ <b>Lex.uz Bot</b>\n\n"
        "O'zbekiston Respublikasi qonunchiligini qidiring va "
        "<b>DOCX</b> formatda yuklab oling.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>Buyruqlar:</b>\n"
        "  /search <i>qonun nomi</i> — hujjat qidirish\n"
        "  /help — yordam\n\n"
        "📌 <b>Inline rejim</b> (istalgan chatda):\n"
        "  <code>@botismi mehnat kodeksi</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Misol:</i>\n"
        "  /search soliq kodeksi\n"
        "  /search fuqarolik kodeksi\n"
        "  /search ta'lim to'g'risida"
    )
    await msg.answer(text, parse_mode=ParseMode.HTML)


# ─── /help ────────────────────────────────────────────
@dp.message(Command("help"))
async def cmd_help(msg: Message):
    text = (
        "📖 <b>Yordam</b>\n\n"
        "<b>1. Oddiy qidiruv:</b>\n"
        "  /search mehnat kodeksi\n\n"
        "<b>2. Inline qidiruv</b> (istalgan chatda):\n"
        "  Chatga <code>@botismi</code> yozing, so'ng qidruv so'zi\n"
        "  Masalan: <code>@botismi soliq</code>\n\n"
        "<b>3. Natijadan:</b>\n"
        "  📄 <i>Hujjat nomini bosing</i> → batafsil ma'lumot\n"
        "  📥 <i>DOCX yuklab olish</i> → fayl yuboriladi\n\n"
        "<b>Hujjat holatlari:</b>\n"
        "  ✅ Amaldagi\n"
        "  ❌ Kuchini yo'qotgan\n"
        "  ⚠️ Amalda emas"
    )
    await msg.answer(text, parse_mode=ParseMode.HTML)


# ─── /search ──────────────────────────────────────────
@dp.message(Command("search"))
async def cmd_search(msg: Message):
    query = msg.text.split(None, 1)[1].strip() if len(msg.text.split()) > 1 else ""
    if not query:
        await msg.answer(
            "❗ Qidiruv so'zini kiriting.\n"
            "Misol: <code>/search mehnat kodeksi</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    await _do_search(msg, query)


@dp.message(F.text & ~F.text.startswith("/"))
async def msg_search(msg: Message):
    """Oddiy matn — avtomatik qidiruv."""
    query = msg.text.strip()
    if len(query) >= 3:
        await _do_search(msg, query)


async def _do_search(msg: Message, query: str):
    """Qidiruv va natijalarni ko'rsatish."""
    loading = await msg.answer(
        f"🔍 <b>{query}</b> qidirilmoqda...",
        parse_mode=ParseMode.HTML,
    )

    results = await scraper.search(query)

    if not results:
        await loading.edit_text(
            f"😔 <b>{query}</b> bo'yicha hujjat topilmadi.\n\n"
            f"🔗 <a href='{SEARCH_URL}?query={query}&lang=4'>Lex.uz da qidirish</a>",
            parse_mode=ParseMode.HTML,
        )
        return

    text = f"📋 <b>{query}</b> — {len(results)} ta natija:\n\n"
    kb_rows = []

    for i, doc in enumerate(results, 1):
        s  = STATUS_EMOJI.get(doc["status"], "❓")
        de = DOC_TYPE_EMOJI.get(doc.get("type", ""), "📄")
        dt = f" · {doc['date']}" if doc.get("date") else ""
        text += f"{i}. {s} {de} {doc['title'][:70]}{dt}\n"

        kb_rows.append([
            InlineKeyboardButton(
                text=f"{s} {doc['title'][:40]}",
                callback_data=f"info:{doc['id']}",
            )
        ])

    kb_rows.append([
        InlineKeyboardButton(
            text="🔎 Lex.uz da ko'rish",
            url=f"{SEARCH_URL}?query={query}&lang=4",
        )
    ])

    await loading.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


# ─── Callback: hujjat ma'lumoti ───────────────────────
@dp.callback_query(F.data.startswith("info:"))
async def cb_doc_info(call: CallbackQuery):
    doc_id = call.data.split(":", 1)[1]
    await call.answer("⏳ Yuklanmoqda...")

    info = await scraper.get_doc_info(doc_id)
    if not info:
        await call.message.answer("❌ Ma'lumot topilmadi.")
        return

    await call.message.answer(
        doc_card_text(info),
        parse_mode=ParseMode.HTML,
        reply_markup=doc_action_keyboard(doc_id),
        disable_web_page_preview=True,
    )


# ─── Callback: DOCX yuklab olish ──────────────────────
@dp.callback_query(F.data.startswith("dl:"))
async def cb_download(call: CallbackQuery):
    doc_id = call.data.split(":", 1)[1]
    await call.answer("📥 Yuklanmoqda, kuting...")

    notice = await call.message.answer("⏳ DOCX tayyorlanmoqda...")

    data = await scraper.download_docx(doc_id)

    if data:
        file = BufferedInputFile(data, filename=f"lex_{doc_id}.docx")
        await notice.delete()
        await call.message.answer_document(
            file,
            caption=(
                f"✅ <b>DOCX tayyor!</b>\n"
                f"🔗 <a href='{BASE_URL}/docs/{doc_id}'>Lex.uz da ochish</a>"
            ),
            parse_mode=ParseMode.HTML,
        )
    else:
        # Login kerak bo'lgan yoki boshqa muammo
        await notice.edit_text(
            "⚠️ <b>Avtomatik yuklab bo'lmadi.</b>\n\n"
            "Lex.uz saytida login talab qilinishi mumkin.\n"
            "Quyidagi tugmani bosib, saytda "
            "<i>«MS Word ga saqlash»</i> (💾) ikonkasini bosing:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📄 Lex.uz da ochish va yuklab olish",
                    url=f"{BASE_URL}/docs/{doc_id}",
                )]
            ]),
        )


# ═══════════════════════════════════════════════════════
#  INLINE MODE
# ═══════════════════════════════════════════════════════
@dp.inline_query()
async def inline_handler(iq: InlineQuery):
    query = iq.query.strip()

    # Qisqa so'rov
    if len(query) < 2:
        await iq.answer(
            [],
            switch_pm_text="🔍 Qidiruv uchun kamida 2 harf kiriting",
            switch_pm_parameter="start",
            cache_time=5,
        )
        return

    results = await scraper.search(query)
    inline_items = []

    for doc in results:
        s_emoji = STATUS_EMOJI.get(doc.get("status", "Y"), "❓")
        s_label = STATUS_LABEL.get(doc.get("status", "Y"), "")
        d_emoji = DOC_TYPE_EMOJI.get(doc.get("type", ""), "📄")
        date    = doc.get("date", "")
        num     = doc.get("num", "")

        # Inline sarlavha (50 belgigacha)
        item_title = f"{s_emoji} {doc['title']}"[:80]

        # Qisqa tavsif
        desc_parts = [s_label]
        if date:
            desc_parts.append(date)
        if num:
            desc_parts.append(num)
        description = " · ".join(desc_parts)

        # Xabar matni
        msg_text = doc_card_text(doc)

        inline_items.append(
            InlineQueryResultArticle(
                id=doc["id"],
                title=item_title,
                description=description or "Lex.uz hujjati",
                input_message_content=InputTextMessageContent(
                    message_text=msg_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📥 DOCX yuklab olish",
                            callback_data=f"dl:{doc['id']}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="🌐 Lex.uz da ochish",
                            url=doc["url"],
                        ),
                    ],
                ]),
                thumb_url=f"https://lex.uz/assets/img/lex_uz.svg",
                url=doc["url"],
            )
        )

    if not inline_items:
        # Hech narsa topilmadi
        inline_items = [
            InlineQueryResultArticle(
                id="not_found",
                title="😔 Hujjat topilmadi",
                description=f'"{query}" bo\'yicha natija yo\'q',
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"❌ <b>{query}</b> bo'yicha hujjat topilmadi.\n\n"
                        f"🔗 <a href='{SEARCH_URL}?query={query}&lang=4'>"
                        f"Lex.uz da qidirish</a>"
                    ),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                ),
            )
        ]

    await iq.answer(
        inline_items,
        cache_time=120,
        is_personal=False,
    )


# ═══════════════════════════════════════════════════════
#  WEBHOOK (Render uchun)
# ═══════════════════════════════════════════════════════
async def on_startup(app: web.Application):
    """Startup: webhook o'rnatish."""
    full_url = WEBHOOK_URL.rstrip("/") + WEBHOOK_PATH
    await bot.set_webhook(full_url, drop_pending_updates=True)
    logger.info(f"✅ Webhook set: {full_url}")


async def on_shutdown(app: web.Application):
    """Shutdown: tozalash."""
    await bot.delete_webhook()
    await scraper.close()
    await bot.session.close()
    logger.info("👋 Bot stopped.")


# ─── Health check endpoint (Render keepalive) ──────
async def health_check(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "bot": "lexuz"})


# ═══════════════════════════════════════════════════════
#  ASOSIY ENTRY POINT
# ═══════════════════════════════════════════════════════
def main():
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN muhit o'zgaruvchisi o'rnatilmagan!")

    # Webhook rejimi (Render)
    if WEBHOOK_URL:
        logger.info("🌐 Webhook rejimida ishga tushmoqda...")

        app = web.Application()
        app.router.add_get("/", health_check)
        app.router.add_get("/health", health_check)

        # Webhook handler
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

        app.on_startup.append(on_startup)
        app.on_shutdown.append(on_shutdown)

        web.run_app(app, host="0.0.0.0", port=PORT)

    # Polling rejimi (lokal ishlab chiqish)
    else:
        logger.info("🔄 Polling rejimida ishga tushmoqda (lokal)...")

        async def polling():
            await bot.delete_webhook(drop_pending_updates=True)
            try:
                await dp.start_polling(bot)
            finally:
                await scraper.close()
                await bot.session.close()

        asyncio.run(polling())


if __name__ == "__main__":
    main()
