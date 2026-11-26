# Keepsake

Free downloader for public Instagram posts and reels. Frontend on GitHub Pages, backend on Render's free tier.

```
frontend/index.html   -> GitHub Pages
backend/app.py        -> Render (Flask + yt-dlp + instaloader)
render.yaml           -> Render blueprint
```

## 1. Push to GitHub
Create a repo (e.g. `keepsake`) and push this whole folder.

## 2. Deploy the backend (Render, free)
1. Sign in at render.com with GitHub.
2. New > Blueprint > pick your repo. Render reads `render.yaml`.
3. When asked for `ALLOWED_ORIGINS`, enter `https://YOUR-GITHUB-USERNAME.github.io`
4. Deploy. Copy the URL, e.g. `https://keepsake-api.onrender.com`.
5. Open that URL: you should see `{"status":"ok"}`.

(No blueprint? New > Web Service, root directory `backend`, build `pip install -r requirements.txt`, start `gunicorn app:app --timeout 120 --workers 1 --threads 4`.)

## 3. Connect the frontend
In `frontend/index.html`, change:
```js
const API = "https://YOUR-APP-NAME.onrender.com";
```
to your Render URL. Commit and push.

## 4. Turn on GitHub Pages
Repo > Settings > Pages > Deploy from a branch > `main`, folder `/ (root)`.
Because the page is in `frontend/`, either move `index.html` to the repo root, or choose a GitHub Actions deploy of the `frontend` folder. Your site will be at `https://YOUR-USERNAME.github.io/keepsake/`.

## When it stops working
- Free Render servers sleep after ~15 minutes. The first request takes up to a minute.
- Instagram changes often. On Render: Manual Deploy > "Clear build cache & deploy" to pull the latest `yt-dlp`.
- If Instagram demands a login, set an `IG_COOKIES` environment variable to a Netscape-format cookies.txt exported from a spare account. Use a throwaway account, not your main one; it can get flagged.
- Instagram may block shared server IPs. That is the main reason paid sites charge credits: they pay for proxies.

## Use responsibly
Only save content you own or have permission to use.
