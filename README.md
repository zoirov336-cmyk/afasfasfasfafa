# ZERUX AFK BOT

Minecraft serverlar uchun AFK bot. Hamma foydalana oladi:

1. Botga `/start` yozing.
2. Bot so'raydi: **server IP -> port -> username**.
3. Bot serverga kirib, **3 kun** AFK bo'lib turadi.
4. `/status` bilan tekshiring. 3 kundan keyin yana `/start` yozing.

## Buyruqlar
- `/start` - AFK botni boshlash
- `/status` - holat (server, username, ulanish, qolgan vaqt)
- `/time` - qolgan vaqt
- `/stop` - to'xtatish
- `/cancel` - savol-javobni bekor qilish

## Fayllar
| Fayl | Vazifasi |
|---|---|
| `bot.py` | Telegram bot |
| `mc_client.js` | Minecraft klient (mineflayer, 1.8 - 1.21+, versiya avtomatik) |
| `package.json` | Node kutubxonalari |
| `requirements.txt` | Python kutubxonalari |
| `Dockerfile` | Railway uchun (Python + Node) |
| `Procfile` | Namuna |
| `.env.example` | Variables namunasi |

## Railway'da ishga tushirish
1. https://railway.app da akkaunt oching.
2. Fayllarni GitHub repoga yuklang.
3. **New Project -> Deploy from GitHub Repo**.
4. **Variables** ga `TELEGRAM_BOT_TOKEN` ni qo'shing (@BotFather -> `/newbot`).
5. **Deploy** tugmasini bosing.

## Variables
| Nomi | Standart | Izoh |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | - | majburiy |
| `AFK_HOURS` | 72 | AFK davomiyligi (3 kun) |
| `MAX_SESSIONS` | 50 | bir vaqtda eng ko'p bot (Railway resursini himoya qiladi) |
| `TZ_OFFSET` | 5 | vaqt zonasi (UTC+5) |
| `DB_PATH` | afk.db | Volume ulasangiz `/data/afk.db` |
| `RECONNECT_DELAY` | 15 | uzilsa qayta ulanish oralig'i (sek) |
| `MAX_FAILS` | 20 | ketma-ket ulana olmasa to'xtatish |

## Muhim
- Faqat **offline-mode (cracked)** serverlar yoki whitelist'ga username qo'shilgan serverlar.
  Litsenziyali (online-mode) serverlarga ulanib bo'lmaydi.
- Parol (AuthMe `/login`) talab qiladigan serverlarda bot kira olmaydi.
- Bot faqat shaxsiy chatda ishlaydi (IP boshqalarga ko'rinmasligi uchun).
- Lokal/ichki manzillar (127.0.0.1, 192.168.x.x va h.k.) bloklangan.
- Railway'da fayllar qayta deploy qilinganda o'chadi. AFK sessiyalari saqlanishi uchun Volume ulab,
  `DB_PATH=/data/afk.db` qiling.
- Faqat o'z serveringizda yoki ruxsat bergan serverlarda ishlating.
