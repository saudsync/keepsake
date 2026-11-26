# Keepsake

Free downloader for public Instagram posts and reels. The frontend is hosted with GitHub Pages, and the backend runs on Render.

```text
keepsake/
├── docs/
│   └── index.html        ← GitHub Pages website
├── backend/
│   ├── app.py            ← Render API
│   └── requirements.txt
├── render.yaml
└── README.md
```

## Deploy the backend

1. Sign in to Render and create a new Blueprint.
2. Select this repository.
3. Set `ALLOWED_ORIGINS` to `https://YOUR-GITHUB-USERNAME.github.io`.
4. Deploy and copy the generated service URL.

## Connect the frontend

In `docs/index.html`, replace:

```js
const API = "https://YOUR-APP-NAME.onrender.com";
```

with your Render service URL.

## Enable GitHub Pages

In the repository settings, open **Pages** and deploy from the `main` branch using the `/docs` folder.

## Use responsibly

Only save content you own or have permission to use.
