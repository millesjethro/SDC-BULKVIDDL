const form = document.querySelector("#connect");
const codeInput = document.querySelector("#code");
const status = document.querySelector("#status");
const button = form.querySelector("button");

const platforms = {
  instagram: { label: "Instagram", urls: ["https://www.instagram.com/"],
    required: ["sessionid"], optional: ["csrftoken"] },
  threads: { label: "Threads", urls: ["https://www.threads.com/", "https://www.threads.net/"],
    required: ["sessionid"], optional: ["csrftoken", "ds_user_id", "mid", "ig_did", "ig_nrcb"] },
  facebook: { label: "Facebook", urls: ["https://www.facebook.com/"],
    required: ["c_user", "xs"], optional: ["datr", "sb", "fr"] },
};

async function readSession({ urls, required, optional }) {
  const names = [...required, ...optional];
  for (const url of urls) {
    const entries = await Promise.all(names.map(async (name) => {
      const cookie = await chrome.cookies.get({ url, name });
      return [name, cookie?.value];
    }));
    const cookies = Object.fromEntries(entries.filter(([, value]) => value));
    if (required.every((name) => cookies[name])) return cookies;
  }
  return null;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const match = /^([0-9]{1,5}):([a-f0-9]{48})$/.exec(codeInput.value.trim());
  if (!match || Number(match[1]) < 1 || Number(match[1]) > 65535) {
    status.textContent = "Copy a pairing code from Connect Chrome in the downloader.";
    return;
  }
  button.disabled = true;
  status.textContent = "Connecting…";
  try {
    const platform = document.querySelector("#platform").value;
    const service = platforms[platform];
    const cookies = await readSession(service);
    if (!cookies) {
      status.textContent = "Sign in to " + service.label + " in this Chrome profile, then try again.";
      return;
    }
    const response = await fetch("http://127.0.0.1:" + Number(match[1]) + "/api/chrome-session", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Pair-Code": match[2] },
      body: JSON.stringify({ platform, cookies }),
      credentials: "omit",
      redirect: "error",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      status.textContent = response.status === 403
        ? "Generate a new pairing code in the downloader."
        : "The downloader could not accept this session.";
      return;
    }
    codeInput.value = "";
    status.textContent = service.label + " connected. Add or retry your link in the downloader.";
  } catch {
    status.textContent = "Could not reach the downloader. Keep it open and try again.";
  } finally {
    button.disabled = false;
  }
});
