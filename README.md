# snack

snack is a visible system monitor and admin agent for machines you own or administer. One process watches one host, samples CPU, memory, disk, load, and uptime, and accepts a small set of commands from a Telegram bot. Access is fail-closed: only chat IDs you list can talk to it, and the only things it will start, stop, or run are names you put in `snack.yaml`.

It prints a banner when it starts, logs to stdout (and optionally a file), and shows up as a normal process and, if you install the example unit, as a normal systemd service.

## What this is

- A consent-based admin helper. Install it yourself, on hosts you administer, and tell the people who use that machine.
- A health reporter with thresholds and cooldown so a full disk pages Telegram without flooding the chat.
- A whitelist runner. `/run disk` executes the argv you configured for `disk`. `/start_service nginx` controls the systemd unit you mapped to the name `nginx`.
- One agent process per machine. Replies are tagged with the hostname so you can run it on more than one host later and still tell them apart.

## What this is not

snack is not a remote-access toolkit and it is not built to hide.

- It does not conceal itself from the process list, the journal, or the person at the machine.
- It does not record keyboard input, take screenshots, read the webcam, or ship arbitrary files off the host.
- It does not open a shell, reverse or otherwise. There is no "run this string" command.
- It does not install silent persistence. The optional unit file is an ordinary `Type=simple` service you enable yourself.
- It will not talk to chats that are not on the allowlist.

If you need a stealth agent, this project will not provide one.

## Requirements

- Python 3.11 or newer
- A Telegram account and a bot token from [@BotFather](https://t.me/BotFather)
- Linux with systemd for service start/stop/restart. Health metrics work on Linux and macOS (`psutil`). On macOS and Windows, service commands reply with a clear "systemd required" error and do nothing else.

## 1. Create a bot and get a token

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts.
3. BotFather replies with a token that looks like `123456789:AAH...`. That token is a password. Keep it in an environment variable or a root-only env file, not in git.

Anyone who has the token can operate the bot, including reading updates and sending messages as it. If it leaks, revoke it in BotFather (`/revoke`) and put the new value in `TELEGRAM_BOT_TOKEN`.

## 2. Find your chat ID

The agent ignores every chat except the IDs you configure. Your numeric chat ID is not the same as your @username.

1. Finish the install below far enough to have a token in the environment.
2. Open your bot in Telegram and send `/start`.
3. On the machine, with the agent **not** running (Telegram allows only one `getUpdates` client at a time):

```bash
snack chats --config snack.yaml
```

You should see a line like:

```text
chat_id=123456789 type=private from=@yourname
```

Put `123456789` in `telegram.allowed_chat_ids` or in `SNACK_ALLOWED_CHAT_IDS`. Group and supergroup IDs are negative; if you add one, every member of that group can run the whitelist unless you also set `allowed_usernames`.

`snack chats` only prints IDs on the local terminal. It does not add them to the allowlist for you.

## 3. Install

From a clone of this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

To run the tests as well:

```bash
pip install -e ".[dev]"
pytest
```

The console script is `snack`. `python -m snack` does the same thing.

## 4. Configure

```bash
cp snack.example.yaml snack.yaml
cp .env.example .env
```

Edit `.env`:

```bash
TELEGRAM_BOT_TOKEN=123456789:replace-with-the-real-token
SNACK_ALLOWED_CHAT_IDS=123456789
```

Environment variables override the YAML file. Prefer them for the token so `snack.yaml` stays free of secrets. `snack.yaml` is gitignored; `snack.example.yaml` is the template.

Then edit `snack.yaml`:

- `telegram.allowed_chat_ids` — required if `SNACK_ALLOWED_CHAT_IDS` is unset. At least one ID.
- `telegram.allowed_usernames` — optional extra restriction. Leave it empty to allow any user in the allowed chats.
- `services` — names you are willing to start, stop, and restart, each mapped to a systemd unit.
- `commands` — names mapped to a fixed argument list. See below.
- `alerts` — thresholds. `null` turns one check off. A sample at or above the threshold alerts.
- `agent.sample_interval_seconds` — how often the background loop checks (minimum 60 seconds is a good start; the floor is 5).
- `alerts.cooldown_seconds` — minimum gap between repeat alerts of the same type while it stays over the line.

`snack check-config --config snack.yaml` prints a summary and refuses to show the token. Fix any errors before starting.

Load the env file in your shell when you run snack by hand:

```bash
set -a
source .env
set +a
```

## 5. Run

```bash
snack
# or
snack run --config snack.yaml
```

You should see a banner like this on the terminal, and a JSON log line with `"msg": "monitoring active"`:

```text
============================================================
 snack — consent-based system monitor
 This process is visible on purpose.
 Use it only on machines you own or administer.
 Monitoring active.
 config: snack.yaml
 host:   web-01
 allowlist: 1 chat id(s)
============================================================
```

If `notify_on_start` is true (the default), each allowed chat also gets a "snack monitoring active" message. That only arrives after you have opened the bot and pressed Start at least once; Telegram will not let a bot message someone first.

Other local commands:

| Command | What it does |
| --- | --- |
| `snack check-config --config snack.yaml` | Validate the file and print a redacted summary |
| `snack sample --config snack.yaml` | Print one health sample locally and exit |
| `snack chats --config snack.yaml` | List recent chat IDs (stop the agent first) |

Stop the agent with Ctrl-C. It prints `snack monitoring stopped.`

Messages sent while snack is stopped are discarded on the next start, so a restart command cannot sit in the queue and fire later.

## 6. Example Telegram session

After the bot is running and your chat ID is on the allowlist:

```text
You: /help
Bot: [web-01] snack — visible system monitor
     This bot answers only an allowlist of chats.
     Commands:
     /help — this message
     /whoami — your chat id and this host
     /status — short health summary
     /health — CPU, memory, disk, load, uptime
     /services — whitelisted services and their status
     /start_service NAME
     /stop_service NAME
     /restart_service NAME
     /run NAME — run one named command
     Services: nginx
     Commands: disk, uptime
     Names must match the config exactly. There is no shell.

You: /whoami
Bot: [web-01] chat id: 123456789
     username: @yourname
     user id: 111
     host: web-01
     authorized: yes

You: /status
Bot: [web-01] monitoring active on web-01
     up 3d 4h 12m | cpu 2.1% | mem 41.0% | disk 61.0% | load 0.42

You: /health
Bot: [web-01] health
     Host: web-01
     OS: Linux 6.8.0
     Uptime: 3d 4h 12m
     CPU: 2.1% (4 cores)
     Memory: 41.0% (3.2 GiB / 7.8 GiB)
     Disk (/): 61.0% (48.1 GiB / 78.9 GiB)
     Load: 0.42 0.31 0.28 (1m per CPU 0.11)

You: /services
Bot: [web-01] services
     nginx:
     ● nginx.service - A high performance web server
     Active: active (running)
     ...

You: /restart_service nginx
Bot: [web-01] restart nginx: ok

You: /run disk
Bot: [web-01] run disk (exit 0)
     Filesystem      Size  Used Avail Use% Mounted on
     /dev/sda1        79G   48G   28G  61% /

You: /run uptime
Bot: [web-01] run uptime (exit 0)
     12:01:05 up 3 days, 4:12, 1 user, load average: 0.42, 0.31, 0.28

You: /run anything-else
Bot: [web-01] run anything-else: 'anything-else' is not a whitelisted command. Known: disk, uptime
```

A chat that is not on the allowlist gets only `Not authorized.` The rejected chat ID is written to the local log so you can add it deliberately. It is not granted access.

An alert looks like this, and it will not repeat for that metric until `cooldown_seconds` has passed:

```text
[web-01] ALERT disk: disk / 93.2% (threshold 90%)
[web-01] RECOVERED disk: back under the threshold
```

If the metric stays high, snack sends one reminder after the cooldown, marked "still over threshold". A value that crosses the line, recovers, and crosses again inside the cooldown is suppressed so a flapping disk does not page you on every sample.

## 7. Run it as a visible systemd service

The unit in `deploy/snack.service` is a normal service. It stays in `systemctl status` and `journalctl`. It is not a hidden unit.

```bash
sudo useradd --system --home-dir /var/lib/snack --create-home snack
sudo mkdir -p /etc/snack /opt/snack
sudo python3 -m venv /opt/snack/.venv
sudo /opt/snack/.venv/bin/pip install /path/to/this/repo
sudo cp snack.yaml /etc/snack/snack.yaml
sudo cp deploy/snack.service /etc/systemd/system/snack.service
```

Create `/etc/snack/snack.env` (mode `0600`, owner root) instead of putting the token in the unit file:

```bash
TELEGRAM_BOT_TOKEN=123456789:replace-me
SNACK_ALLOWED_CHAT_IDS=123456789
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now snack
systemctl status snack
journalctl -u snack -f
```

Adjust `User=`, `ExecStart=`, and paths in the unit to match where you installed it. Health checks do not need root. `systemctl start` and `stop` for system units do. v1 calls `systemctl` directly, with no sudo wrapper and no `--user` flag. Run the service as a user that is allowed to control the units you listed, or as root if you accept that the whitelist then runs with root. Keep that whitelist short.

## 8. Security notes

- Treat `TELEGRAM_BOT_TOKEN` like a password. Do not commit it, paste it into a chat, or drop it into a `curl` URL that lands in shell history. Prefer `snack chats` over calling the HTTP API by hand.
- If the token leaks, revoke it in BotFather and restart snack with the new one.
- Keep `allowed_chat_ids` to your private chat. An allowed group lets every member run the whitelist. Add `allowed_usernames` if more than one person can reach an allowed chat.
- Never enable an arbitrary shell. snack does not have a switch for that.
- Commands run with the privileges of the snack process, as the exact argv in the config, with a timeout and an output cap. Telegram text is never concatenated into that argv. The only user input is the command or service name, and it must match the config exactly.
- The config loader rejects shell and interpreter command strings (`bash -c`, `python -c`, `env bash -c`, and the same shape for other common shells). A fixed script path such as `["/usr/bin/python3", "/usr/local/sbin/check.py"]` is allowed.
- Review the whitelist when you change it. Do not add `bash`, `sh`, `sudo`, or anything that takes a command string from a file an untrusted user can edit.
- snack logs JSON to stdout and redacts the bot token. Do not add the token to command argv or chat replies. `snack check-config` does not print it either.
- Install snack only on machines you administer, with the owner's informed consent. The banner, the startup Telegram notice, and this README are there so the machine is not quietly enrolled.
- While snack is running it holds the bot's polling session. Don't share that token with another poller.

### Extending the whitelist safely

Add a named entry, restart snack, and try it with `/run NAME` or `/start_service NAME`. v1 does not reload the file live.

```yaml
commands:
  - name: disk
    argv: ["df", "-h"]
    timeout_seconds: 15
  - name: backup_status
    argv: ["/usr/local/sbin/backup-status"]
    timeout_seconds: 60

services:
  - name: nginx
    unit: nginx.service
```

Prefer absolute paths. `df` and `uptime` are resolved from the service user's `PATH`. Names are case-sensitive and limited to letters, digits, `.`, `_`, and `-`. Extra Telegram arguments are rejected, so `/run disk /tmp` does not become `df -h /tmp`.

Service names and unit names are different on purpose. `/start_service web` is allowed only when `web` is the configured name; the unit (`nginx.service`) comes from the file, not from the chat message.

## 9. Logging

Logs are JSON, one object per line, on stdout. Set `agent.log_file` to also append to a file. Levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`. httpx is kept at WARNING because its request URLs contain the bot token; the formatter redacts the token anyway.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The tests cover config loading, the chat allowlist, the command and service whitelists, threshold and cooldown behavior, and the Telegram handlers with a fake update. They do not call Telegram.

## Out of scope for v1

A web dashboard, multi-tenant hosting, screen capture, file transfer, remote desktop, keylogging, and silent auto-update or persistence are intentionally absent.

## License

MIT. See [LICENSE](LICENSE).
