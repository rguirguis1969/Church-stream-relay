# Stream Relay: setup guide

This replaces Restream. Each room's OBS sends **one** stream to a small server you rent. The server copies it to that room's YouTube channel and Facebook page (and anything else you add). The sanctuary and the chapel can stream at the same time, each to their own channels.

```
Sanctuary OBS ──►┐                  ┌──► Sanctuary YouTube + Facebook
                 ├──► Your server ──┤
Chapel OBS    ──►┘                  └──► Chapel YouTube + Facebook
```

**Cost:** about $6 a month for the server. **Time to set up:** about 30 minutes, once.

---

## What you need

- A credit card for the server company.
- About 30 minutes at a computer.
- Your YouTube and Facebook stream keys for each room (you'll paste these into the settings page at the end, so you can get them later).

---

## Step 1: Rent a server (10 minutes)

We'll use **DigitalOcean** because its website is the simplest. (Hetzner is a cheaper option and works the same way.)

1. Go to **digitalocean.com** and create an account.
2. Click **Create → Droplets**.
3. **Region:** pick the one closest to your church.
4. **Image:** choose **Ubuntu 24.04 (LTS)**.
5. **Size:** choose **Basic → Regular → $6/month** (1 GB memory, 1 CPU, 1,000 GB transfer). That's plenty for both rooms.
6. **Authentication:** choose **Password** and make up a strong root password. Write it down.
7. **Hostname:** type something like `church-stream`.
8. Click **Create Droplet**. After about a minute it shows an **IP address** like `164.90.123.45`. Write it down. This is your server's address.

> **Is the server big enough?** Yes. The relay only copies video and never re-encodes it, so it barely uses the processor. Each room sends about 6 Mbps and the server sends that out once per platform. With both rooms live to YouTube and Facebook, that's about 36 Mbps in total, and these servers have 1,000 Mbps connections. A typical month of Sunday services (two rooms, about 2 hours each, two platforms) uses roughly 100 to 150 GB of the 1,000 GB included.

---

## Step 2: Install the relay (10 minutes)

1. On the Droplet's page in DigitalOcean, click **Console** (top right). A black window opens. This is your server.
2. Copy and paste this line into it, then press **Enter**:

   ```
   git clone REPO_URL stream-relay && cd stream-relay && bash install.sh
   ```

3. It installs everything. When it asks *"do you have a web address pointed at this server?"*, just press **Enter** to skip (see "Optional: a secure web address" below if you want one).
4. After a few minutes it prints something like:

   ```
   All done! The stream relay is running.
     Settings page:  http://164.90.123.45:8080
     Password:       Xq81kLmP0aZ7rT2vB9sd
   ```

   **Write down the password.** You can close the console now.

---

## Step 3: Set up your rooms (5 minutes)

1. Open the **Settings page** address in your web browser and sign in with the password.
2. You'll see two rooms already made: **Main sanctuary** and **Chapel**. You can rename them, or add more.
3. For each room:
   - Tick **Send to YouTube** and paste that room's YouTube stream key.
     *(YouTube Studio → Create → Go live → Stream → "Stream key".)*
   - Tick **Send to Facebook** and paste that room's Facebook stream key.
     *(Facebook → Live Producer → "Streaming software" → "Stream key". Use a **persistent** stream key so it doesn't change every week.)*
   - Click **Save**.

You don't need to change the "Server address" boxes. They're already right for YouTube and Facebook.

---

## Step 4: Point OBS at the server (5 minutes, on each room's computer)

1. In OBS, go to **Settings → Stream**.
2. **Service:** choose **Custom…**
3. **Server:** copy it from the settings page (it looks like `rtmp://164.90.123.45/live`).
4. **Stream Key:** copy **that room's** key from the settings page. The sanctuary and chapel have different keys, which is how the server knows which room is which.
5. Click **OK**.

That's it. Press **Start Streaming** in OBS as usual. Within about 10 seconds the room shows **Live from OBS** on the settings page and each platform shows **Sending**.

**Recommended OBS output settings:** Settings → Output → Bitrate **4500 to 6000 Kbps**, Keyframe interval **2 s**. Facebook rejects streams with a keyframe interval above 2 seconds.

---

## Every Sunday

Nothing changes. Start streaming in OBS, and remember to **schedule or start the live event on YouTube and Facebook** as you do today if your channels need that.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| OBS says "Failed to connect to server" | Check the Server and Stream Key in OBS match the settings page exactly. If you recently clicked "New OBS stream key", paste the new one. |
| The settings page won't open | Go to DigitalOcean and make sure the Droplet is on. Then open the Console and run: `cd stream-relay && docker compose up -d` |
| One platform isn't showing the stream | On the settings page, open that room's **More options** and click **Reconnect** for that platform. Also open **Recent messages** under it. A message like "Input/output error" right after connecting usually means the stream key is wrong or the event isn't set up on that platform. |
| A stream key changed | Paste the new one into the settings page and Save. If you're live, that platform reconnects by itself in a few seconds. |
| Forgot the settings page password | Open the Console and run: `grep ADMIN_PASSWORD stream-relay/.env` |

The relay reconnects on its own if YouTube or Facebook drops for a moment, and it starts back up by itself if the server restarts.

---

## Keeping it safe

- Nobody can send video to your server without a room's secret stream key. Wrong keys are refused.
- Nobody can watch the stream from the server; it only forwards to your platforms.
- The settings page needs the password, and locks out anyone who guesses wrong 10 times.
- If you think an OBS stream key was shared, open **More options → New OBS stream key** and paste the new key into that room's OBS.

### Optional: a secure web address for the settings page

Without this, the settings page uses a plain `http://` address. That works, but someone on the same Wi-Fi could in theory see what you type. To get a proper `https://` address:

1. In Bluehost, open your domain's **DNS** settings and add an **A record**: name `relay`, value = your server's IP address.
2. Wait about 15 minutes, then open the DigitalOcean Console and run:
   ```
   cd stream-relay && sed -i 's/^DOMAIN=.*/DOMAIN=relay.yourchurch.org/' .env && bash install.sh
   ```
   (Use your real domain.)
3. Your settings page is now at **https://relay.yourchurch.org**. OBS's Server becomes `rtmp://relay.yourchurch.org/live`. The old IP address still works in OBS too.

---

## Updating the relay later

Open the Console and run:

```
cd stream-relay && git pull && docker compose up -d --build
```

Your rooms, keys and password are kept.

---

## For a technical helper

- Docker Compose, one container: nginx with the RTMP module receives on port 1935; an `on_publish` hook checks the stream key against each room. Each destination is its own `ffmpeg -c copy` process started by `exec_push`, so one platform failing doesn't affect the others, and nginx respawns it after 5 seconds for auto-reconnect. Facebook RTMPS is handled natively by ffmpeg (no stunnel needed).
- Settings page: Flask + waitress on port 8080, password from `ADMIN_PASSWORD` in `.env`, CSRF-protected forms, settings in the `relay-data` Docker volume (`/data/config.json`).
- Ports: 1935/tcp (RTMP in), 8080/tcp (settings page) or 80/443 when `DOMAIN` is set (Caddy with automatic HTTPS; 8080 is then bound to localhost only).
- To run behind an existing reverse proxy, set `ADMIN_BIND=127.0.0.1`, `URL_PREFIX=/relay`, `TRUSTED_PROXY=<proxy IP>` and `COOKIE_SECURE=1` in `.env`.
- Logs: `docker compose logs -f`. Per-destination ffmpeg logs are in `/data/logs/` (stream keys are masked on the settings page).
