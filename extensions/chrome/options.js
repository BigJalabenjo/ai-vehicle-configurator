const DEFAULT_URL = "http://localhost:8080";
const input = document.getElementById("url");
const status = document.getElementById("status");

chrome.storage.sync.get({ appUrl: DEFAULT_URL }, (v) => { input.value = v.appUrl; });

document.getElementById("save").addEventListener("click", () => {
  let value = input.value.trim() || DEFAULT_URL;
  try {
    const url = new URL(value);
    if (!/^https?:$/.test(url.protocol)) throw new Error("http(s) only");
    value = url.origin + url.pathname.replace(/\/$/, "");
  } catch {
    status.style.color = "#e22718";
    status.textContent = "Please enter a valid http(s) address.";
    return;
  }
  chrome.storage.sync.set({ appUrl: value }, () => {
    input.value = value;
    status.style.color = "#20a54f";
    status.textContent = "Saved. Reload the bmw.de tab.";
  });
});
