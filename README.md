# Rip Chat

Voice chat rooms with room codes - Python server for Render.

## Files

```
rip-chat/
├── server.py           ← Python server (deploy this to Render)
├── requirements.txt    ← Python dependencies
└── public/
    └── index.html      ← Give this file to your friends
```

## Deploy to Render

### Step 1: Push to GitHub
1. Create a new GitHub repo
2. Upload `server.py`, `requirements.txt`, and the `public` folder

### Step 2: Create Render Web Service
1. Go to https://render.com
2. Click "New" → "Web Service"
3. Connect your GitHub repo
4. Configure:
   - **Name**: `rip-chat` (or whatever you want)
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python server.py`

### Step 3: Get Your URL
After deploy, Render gives you a URL like:
```
https://rip-chat.onrender.com
```

### Step 4: Update the HTML File
Open `public/index.html` and find this line (near line 80):
```javascript
const SERVER_URL = 'https://YOUR-APP-NAME.onrender.com';
```
Change it to your actual Render URL:
```javascript
const SERVER_URL = 'https://rip-chat.onrender.com';
```

### Step 5: Share with Friends
Send the updated `index.html` file to your friends. They just double-click to open it!

## How to Use

1. Open the HTML file in your browser
2. Enter your username
3. Either:
   - Click "Create Room" to get a 6-letter code
   - Or enter a friend's code and click "Join"
4. Talk!

## Note About Render Free Tier

Render's free tier "spins down" after 15 minutes of no activity. First connection after that takes ~30 seconds to wake up. This is normal!
