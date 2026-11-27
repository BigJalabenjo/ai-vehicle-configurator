# Chrome extension: AI mode for the BMW configurator

Adds an **AI mode** switch to the BMW configurator, at `configure.bmw.de/…/configure/…`, e.g. https://configure.bmw.de/de_DE/configure/U11/11HM. Switching it on reveals the configurator assistant app in an overlay, with a circular transition growing from the switch. Switching it off (or ×, Escape, or a click outside) hides it again, and the conversation is kept for the next time. It doesn't run on other BMW pages.

Unofficial prototype for demos, not affiliated with BMW. Load it unpacked; don't publish it to the Chrome Web Store.

## 1. Let the app be shown in the configurator

In the app's `.env` (repository root), allow the configurator to embed it, then restart:

```bash
EMBED_ORIGINS=https://configure.bmw.de
```

```bash
docker compose up -d
```

What this changes:

* **Framing:** the web server sends `Content-Security-Policy: frame-ancestors 'self' https://configure.bmw.de`. Every other site is still blocked from framing the app.
* **Sign-in cookie** (if `APP_PASSWORD` is set): it becomes `SameSite=None; Secure; Partitioned`. That's the only way Chrome allows a sign-in inside a frame from another site, and "Partitioned" keeps the cookie confined to the configurator context. Signing in inside the overlay and signing in on the app itself are therefore separate.

## 2. Install the extension

1. Open `chrome://extensions` and switch on **Developer mode** (top right).
2. Click **Load unpacked** and choose this folder (`extensions/chrome`). If you loaded an earlier version, click the extension's reload icon.
3. Open the configurator for any model, e.g. https://configure.bmw.de/de_DE/configure/U11/11HM. The **AI mode** switch appears right of the configurator's navigation bar ("Antriebe · Modellvarianten · … · Fertig"), styled as a matching island. If there's no room beside the bar, it sits just below it; on phones, where the bar is hidden, it goes to the top left.
4. With the app on `localhost`, Chrome asks the first time whether the configurator may access devices on your local network. Click **Allow**, otherwise the overlay stays empty. A published app at a public HTTPS address doesn't trigger this prompt.

**Using a published app:** click the extension's **Details → Extension options** and set its address, e.g. `https://configurator.example.com`. The default is `http://localhost:8080`. The published app needs the same `EMBED_ORIGINS` setting and must use HTTPS.

## How it works

* `content.js` runs only on configurator pages. It adds the switch and the overlay inside a closed shadow root, so the configurator's styles and the overlay's can't affect each other.
* The switch is an accessible `role="switch"`. Animations are reduced when the system asks for reduced motion.
* The app runs in an iframe with its own origin, loaded from its own server. The configurator page can't read the conversation, and the app can't read the configurator page.
* Permissions: only `storage`, for the app address. No access to other sites or tabs.
* Microphone: the frame is allowed to ask for it, for the app's hands-free voice mode. Chrome asks once whether the configurator site may use your microphone; nothing is recorded until you click the app's mic button.
