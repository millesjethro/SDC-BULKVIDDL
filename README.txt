VIDEO BULK DOWNLOADER
=====================
1. Extract the entire ZIP to a folder you can write to.
2. Double-click Video Bulk Downloader.exe. It opens in an Edge or Chrome app
   window, or in your default browser. Windows x64 and a browser are required.
   Python, gallery-dl, browser-cookie3, yt-dlp and FFmpeg are bundled.
3. Keep the EXE and the other files and folders together. To put the app on
   your desktop, create a shortcut to the EXE.

Use
- Paste a URL and click +. Choose the date format for automatic file names:
  January 16, 2001, 2001-01-16, or 01-16-2001. If the posted date is unavailable,
  the app uses UNKNOWN.
- Click any file name in the queue to rename it before downloading.
- Folder name field (next to ZIP / NOT ZIP) = the .zip name, or the sub-folder name.
- Excel/CSV: column A = urls, column B = file name (first row may be a header).
- FARMERS FILE NAMING ON:  {Social Media} video captured {today}, and posted {posted date or custom name}
  e.g. YouTube video captured 10-20-2025, and posted 09-01-2024
  Both automatic dates use the selected format.
- Blue button = update yt-dlp. Close the window with its X to quit.

Instagram photos / carousels
- yt-dlp only downloads VIDEOS. For photo slides the app now falls back to gallery-dl
  (included in the app).
- If Instagram asks for login, add your browser to settings.json, e.g.
  "cookies_browser": "firefox"   (also: chrome, edge, brave). Be logged in to Instagram there.
  Firefox is the most reliable; Chrome/Edge may need to be fully closed first.

Threads
- Needs your Threads login: be logged in to Threads in Chrome (or set "cookies_browser": "firefox"/"edge"/"brave"
  in settings.json). The app includes browser_cookie3.
  Newer Chrome/Edge versions may block reading their cookies - Firefox may work. Or paste a cookie header into
  "threads_cookie" in settings.json.
- Posts with several photos/videos show small buttons (video 1, photo 2...) under the card. Green = will download;
  click to skip. One item saves as name.mp4, several as name.mp4, name (2).mp4, ...

Instagram login + choosing items
- Posts Instagram hides ("This content isn't available to everyone") need your login. The app reads your
  Instagram login from Chrome (bundled browser_cookie3) and retries with it automatically.
  Be logged in to Instagram in Chrome. Other browser: "cookies_browser" in settings.json. Or paste your cookies
  into "instagram_cookie" in settings.json, e.g. "sessionid=...; csrftoken=...".
- Instagram posts with several photos/videos get the same buttons as Threads (video 1, photo 2...).
  If the URL includes ?img_index=, only the linked slide is downloaded.
  For collections, use the arrows to browse the photo and video buttons.
  Uses the bundled gallery-dl.


Instagram Stories and Highlights
- Paste a Stories link (/stories/username/ or /stories/username/story_id/),
  a Highlight link (/stories/highlights/id/), or a shared Highlight link (/s/...).
  A link to an individual story opens just that item. For collections, click the
  photo and video buttons in the queue to choose what to save.
- If the app asks for a login, sign in to Instagram in Chrome, connect the
  companion, and retry the item.
  Your account must already be able to view the story or highlight. Expired
  stories may no longer be available.

Connect Chrome for Instagram Stories and Highlights
- In Chrome, open chrome://extensions, enable Developer mode, and click
  Load unpacked. Select the Chrome Extension folder from this ZIP.
- Sign in to Instagram in the same Chrome profile and open the downloader.
- In the downloader, click Connect Chrome to copy the one-time code. Paste it into the
  SDC Bulk Downloader Companion popup and click Send to Downloader.
- Add or retry your Story or Highlight. The connection lasts until the
  downloader exits. Reconnect if Instagram expires the session.

Connect Threads or Facebook
- Load the Chrome Extension folder from this ZIP. If you already have the
  older companion installed, remove it and load this version.
- Sign in to the platform in Chrome. Click Connect Chrome in the app, then
  choose the platform in the extension, paste the new code, and click Send
  to Downloader. Generate a fresh code to connect each platform.
- Add or retry a Threads post or a Facebook video link. Sessions are kept
  separately in memory until the downloader exits.

Instagram Highlight date filter
- Set Highlights and To before adding or importing a Highlight link. Both
  dates are inclusive and use your Windows time zone. To and the file name
  default to today. Leave Highlights blank and To at today for all slides.
  Remove and re-add a queued link to change its date range.

Experimental Facebook Story videos
- Connect Facebook in the Chrome companion, then add a direct HTTPS
  Facebook /stories/ link. This fallback looks for a direct MP4 in
  the signed-in Story page and saves one video. It does not enumerate
  Highlights or save photo Stories.

X / Twitter posts
- Paste a public post's regular share link. Use the buttons on the queue card
  to choose the videos and GIFs to save. Original-post media starts selected,
  and quoted-post media can be selected separately. GIFs save as looping MP4s.
