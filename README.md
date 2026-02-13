# Torrent Server Bot

## Running the bot

1. Create a Python virtual environment:
   ```bash
   python3 -m venv .venv
   ```

2. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install --upgrade pip
   pip install aiogram
   ```

4. Create your local environment file:
   ```bash
   cp .env.example .env
   ```

5. Edit `.env` and set your Telegram bot token:
   ```env
   TELEGRAM_BOT_TOKEN=your_real_bot_token
   ```

6. Start the bot:
   ```bash
   python3 -m app.bot.main
   ```

When the bot is running, send `/start` (or other Phase 1 commands) to your bot in Telegram and check terminal output.
