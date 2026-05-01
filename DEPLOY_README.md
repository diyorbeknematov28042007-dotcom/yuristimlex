# ⚖️ Lex.uz Telegram Bot

O'zbekiston Respublikasi qonunchiligini Telegram orqali qidirish
va **DOCX** formatda yuklab olish boti.

---

## 🚀 Render.com ga Deploy Qilish

### 1-qadam: Bot yaratish
1. [@BotFather](https://t.me/BotFather) ga yozing
2. `/newbot` → nom → username
3. **Token** ni saqlang: `123456789:ABCdef...`
4. `/setinline` → botingizni tanlang → **Yoqish**
5. Inline placeholder: `mehnat kodeksi`

### 2-qadam: GitHub ga yuklash
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/SIZNING/lexuz-bot.git
git push -u origin main
```

### 3-qadam: Render.com sozlash
1. [render.com](https://render.com) → **New** → **Web Service**
2. GitHub repozitoriyangizni ulang
3. Sozlamalar:
   - **Name:** `lexuz-telegram-bot`
   - **Region:** Frankfurt
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
4. **Environment Variables** qo'shing:

| Kalit | Qiymat |
|-------|--------|
| `BOT_TOKEN` | `123456789:ABCdef...` |
| `WEBHOOK_URL` | `https://lexuz-telegram-bot.onrender.com` |
| `PORT` | `10000` |

5. **Create Web Service** tugmasini bosing

### 4-qadam: Tekshirish
- Render logs ni kuzating
- Telegramda botga `/start` yuboring

---

## 💻 Lokal Ishlab Chiqish

```bash
# O'rnatish
pip install -r requirements.txt

# .env fayl yaratish
echo "BOT_TOKEN=123456789:ABCdef..." > .env

# Ishga tushirish (polling rejimi - WEBHOOK_URL bo'lmasa)
python bot.py
```

---

## 📱 Bot Imkoniyatlari

### Buyruqlar
```
/start   — Bosh sahifa
/help    — Yordam
/search  QIDIRUV — Hujjat qidirish
```

### Inline rejim
Istalgan chatda:
```
@botismi mehnat kodeksi
@botismi soliq kodeksi
@botismi fuqarolik
@botismi ta'lim to'g'risida
```

### Natija ko'rinishi
```
✅ ⚖️ Mehnat kodeksi
   Amaldagi · 30.03.2020 · ORQ-613

[📥 DOCX yuklab olish]
[🌐 Lex.uz da ochish]
```

---

## 🏗️ Fayl Tuzilishi

```
lexuz_bot/
├── bot.py           # Asosiy bot kodi
├── requirements.txt # Python kutubxonalar
├── render.yaml      # Render deploy config
└── README.md        # Shu fayl
```

---

## ⚠️ Eslatmalar

- **DOCX yuklab olish** — Lex.uz login talab qilsa, bot saytga yo'naltiradi
- **Render Free Plan** — 15 daqiqa harakatsizlikdan so'ng uyquga ketadi.
  Buning oldini olish uchun [UptimeRobot](https://uptimerobot.com) bilan
  har 10 daqiqada `/health` endpointga ping yuboring.
- **Rate limiting** — Ko'p so'rov yubormang, IP bloklanishi mumkin

---

## 🔧 Muammolar va Yechimlar

| Muammo | Yechim |
|--------|--------|
| Bot javob bermayapti | Render logs ni tekshiring |
| Webhook error | `WEBHOOK_URL` to'g'riligini tekshiring |
| 403 Forbidden | Lex.uz IP ni bloklagan — VPS IP ni o'zgartiring |
| DOCX yuklanmaydi | Lex.uz login talab qiladi, saytni qo'lda oching |
