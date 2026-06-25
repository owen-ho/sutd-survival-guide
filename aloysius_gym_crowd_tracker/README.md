# 🏋️ Gym Crowd Tracker Telegram Bot

A Telegram bot that tracks gym occupancy using student card tap data, helping students check crowd levels before visiting the gym.

## Features

- **Real-time Gym Status**: Check current occupancy with visual indicators
- **Entry/Exit Tracking**: Track student entries and exits via card taps
- **Activity History**: View recent gym activity
- **Occupancy Levels**: Color-coded crowd levels (🟢 Low, 🟡 Medium, 🟠 High, 🔴 Full)
- **Daily Statistics**: Track total entries and exits per day

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with instructions |
| `/status` | Check current gym crowd level |
| `/recent` | View recent gym activity |
| `/popular` | See popular time slots |
| `/simulate_entry ID` | Simulate card tap on entry (staff) |
| `/simulate_exit ID` | Simulate card tap on exit (staff) |
| `/admin_reset` | Reset daily counters (admin) |

## Setup Instructions

### 1. Create Your Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow the prompts to name your bot and get a username
4. **Save the bot token** that BotFather provides

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure the Bot

Set your bot token using an environment variable:

**Windows (Command Prompt):**
```cmd
set BOT_TOKEN=your_bot_token_here
```

**Windows (PowerShell):**
```powershell
$env:BOT_TOKEN = "your_bot_token_here"
```

**Linux/Mac:**
```bash
export BOT_TOKEN="your_bot_token_here"
```

Or edit the `config.py` file and replace `YOUR_BOT_TOKEN_HERE` with your actual bot token.

### 4. Run the Bot

```bash
python bot.py
```

## Configuration

Edit `config.py` to customize:

- `MAX_GYM_CAPACITY` - Maximum number of people allowed in the gym
- `OCCUPANCY_LEVELS` - Customize crowd level thresholds
- `DATA_FILE` - JSON file for storing gym data

## Project Structure

```
├── bot.py              # Main Telegram bot code
├── gym_tracker.py      # Gym occupancy tracking logic
├── config.py           # Configuration settings
├── requirements.txt    # Python dependencies
├── gym_data.json       # Auto-generated data storage
└── README.md           # This file
```

## How It Works

1. **Students** use `/status` to check gym occupancy before heading over
2. **Gym entry** is tracked when students tap their cards (simulated with `/simulate_entry`)
3. **Gym exit** is tracked when students leave (simulated with `/simulate_exit`)
4. The bot stores data in `gym_data.json` for persistence

## Future Enhancements

- Integration with actual card reader hardware
- Historical analytics and peak hour predictions
- Push notifications when gym gets crowded
- User registration and personalized stats
- Web dashboard for administrators

## License

This project is open-source for educational purposes.