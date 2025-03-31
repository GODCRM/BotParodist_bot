# Bot Parodist - Telegram Bot for Voice Synthesis

A Telegram bot that generates voice messages using text-to-speech technology, specifically designed to create parodies with a distinctive voice style.

## ⚠️ Requirements

- Python 3.10 (strictly required)
- FFmpeg (for audio processing)

## 🚀 Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/BotParodist_bot.git
cd BotParodist_bot
```

2. Create and activate a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
```

3. Install required packages:
```bash
pip install -r requirements.txt
```

## 📦 Required Python Packages

The following packages are required (versions are specified in requirements.txt):
- python-telegram-bot
- TTS (Text-to-Speech)
- psutil (optional, for memory monitoring)

## ⚙️ Configuration

1. Create a `config.json` file in the project root with the following structure:
```json
{
    "token": "YOUR_TELEGRAM_BOT_TOKEN",
    "max_text_length": 500,
    "min_text_length": 3,
    "max_queue_size": 3,
    "path_default_sempl_voice": "p.wav"
}
```

2. Place your voice sample file (`p.wav`) in the project root directory.

## 🎯 Usage

1. Start the bot:
```bash
python aittsbot.py
```

2. In Telegram, start a chat with your bot and use the following commands:
- `/start` - Get information about the bot and its capabilities
- `/gen <text>` - Generate a voice message from the provided text
- `/status` - Check the current status of the bot and queue

## ⚡ Features

- Text-to-speech voice generation
- Queue system for handling multiple requests
- Memory usage monitoring
- Status tracking and reporting
- Automatic cleanup of temporary files

## 📝 Limitations

- Maximum text length: 500 characters
- Minimum text length: 3 characters
- Maximum queue size: 3 tasks
- Voice generation is CPU-intensive and may take some time

## 🔒 Security Notes

- Keep your bot token secure and never share it publicly
- The voice sample file should be kept private and not distributed

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## ⚠️ Disclaimer

This bot is for entertainment purposes only. Please ensure compliance with local laws and regulations regarding voice synthesis and parody content.
