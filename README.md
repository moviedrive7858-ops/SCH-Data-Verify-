# Telegram Data Viewer Bot

Google Spreadsheet data ကို Telegram bot မှတဆင့် ကြည့်ရှုနိုင်သော bot ဖြစ်ပါသည်။

## Features

- `/check_data` command ဖြင့် Sheet 3 ခု (Profile, Stock, Testing) ကို ရွေးချယ်ကြည့်ရှုနိုင်
- Township → RHC → Sub-center → Village hierarchy navigation
- Profile: Provider Name, Phone, HH, Pop, Lat/Long ပြသ
- Stock: Monthly RDT, ACT, CQ, PQ data ပြသ
- Testing: Monthly Testing, Pf, Pv, Mix, NTG, Refer + Yearly Total ပြသ
- Back button, pagination, 2 min auto-delete, user session management

## Setup

### 1. Google Service Account ဖန်တီးခြင်း

1. [Google Cloud Console](https://console.cloud.google.com/) သို့ သွားပါ
2. Project အသစ်ဖန်တီးပါ (သို့) ရှိပြီးသား project ကိုရွေးပါ
3. **APIs & Services** > **Library** > "Google Sheets API" ကို Enable လုပ်ပါ
4. **APIs & Services** > **Credentials** > **Create Credentials** > **Service Account**
5. Service Account ဖန်တီးပြီး JSON key download ရယူပါ
6. Google Spreadsheet ကို ထို Service Account ၏ email ဖြင့် Share (Viewer) ပေးပါ

### 2. Environment Variables

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram Bot Token (@BotFather မှ ရယူပါ) |
| `OWNER_ID` | Owner Telegram User ID (default: 8714578868) |
| `GOOGLE_SPREADSHEET_URL` | Google Spreadsheet URL |
| `GOOGLE_SERVICE_ACCOUNT_CREDENTIALS` | Service Account JSON file ၏ content တစ်ခုလုံး |

### 3. Render တွင် Deploy ခြင်း

1. GitHub repo ဖန်တီးပြီး code တင်ပါ
2. [Render.com](https://render.com) တွင် **New > Web Service** ဖန်တီးပါ
3. GitHub repo ကို ချိတ်ဆက်ပါ
4. **Build Command**: `pip install -r requirements.txt`
5. **Start Command**: `python3 bot.py`
6. Environment Variables များ ထည့်သွင်းပါ
7. Deploy ပါ

## File Structure

```
├── bot.py              # Main bot logic
├── gsheet_data.py      # Google Sheet data reader
├── keep_alive.py       # Flask keep-alive for Render
├── requirements.txt    # Python dependencies
├── Procfile            # Render process file
└── README.md           # This file
```
