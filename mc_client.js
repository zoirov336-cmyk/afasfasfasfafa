// Minecraft klient: bitta AFK bot. bot.py tomonidan ishga tushiriladi.
// Argumentlar: host port username   (versiya avtomatik aniqlanadi)
const mineflayer = require('mineflayer');

const [, , host, port, username] = process.argv;

function emit(type, extra = {}) {
  process.stdout.write(JSON.stringify({ type, ...extra }) + '\n');
}

let bot;
try {
  bot = mineflayer.createBot({
    host,
    port: parseInt(port, 10),
    username,
    auth: 'offline',
    hideErrors: true,
    checkTimeoutInterval: 120000, // lag bo'lsa ham uzilib qolmasligi uchun
    physicsEnabled: false,        // bot tushmaydi/yurmaydi: "Invalid move player packet" dan saqlaydi
  });
  bot.physicsEnabled = false;
} catch (e) {
  emit('error', { message: String(e && e.message) });
  process.exit(1);
}

const watchdog = setTimeout(() => {
  emit('error', { message: 'ulanish vaqti tugadi' });
  process.exit(1);
}, 60000);

function plain(reason) {
  try {
    let r = reason;
    if (typeof r === 'string') {
      try { r = JSON.parse(r); } catch (_) { return r; }
    }
    const ChatMessage = require('prismarine-chat')(bot.registry);
    return ChatMessage.fromNotch(r).toString();
  } catch (_) {
    return typeof reason === 'string' ? reason : JSON.stringify(reason);
  }
}

let spawned = false;
bot.on('spawn', () => {
  if (spawned) return;
  spawned = true;
  clearTimeout(watchdog);
  emit('online');
  // Anti-AFK: harakatsiz (fizikasiz), faqat qo'l silkitish va hotbar almashtirish
  setInterval(() => {
    try { bot.swingArm('right'); } catch (_) {}
  }, 30000);
  setInterval(() => {
    try { bot.setQuickBarSlot(((bot.quickBarSlot || 0) + 1) % 9); } catch (_) {}
  }, 60000);
});

bot.on('kicked', (reason) => emit('kicked', { reason: String(plain(reason)).slice(0, 200) }));
bot.on('error', (e) => {
  emit('error', { message: String(e && e.message) });
  setTimeout(() => process.exit(1), 500);
});
bot.on('end', (reason) => {
  emit('end', { reason: String(reason) });
  setTimeout(() => process.exit(0), 200);
});

process.on('SIGTERM', () => process.exit(0));
process.on('uncaughtException', (e) => {
  emit('error', { message: String(e && e.message) });
  process.exit(1);
});
