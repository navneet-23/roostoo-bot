# Deploying to AWS (Sydney)

The competition key is used only by the bot on this instance. It is never typed into a
laptop, never committed, and never used by hand. Every behaviour change reaches the instance
as a commit followed by `git pull` and a service restart.

## 1. Launch the instance

1. AWS console, region **Asia Pacific (Sydney) ap-southeast-2**.
2. EC2 → Instances → **Launch instance from template** → choose **Hackathon-Starter-Template**.
3. Key pair: **Proceed without a key pair** (access is via Session Manager).
4. Launch. Wait until the instance shows *Running* and the status checks pass.

## 2. Connect

EC2 → select the instance → **Connect** → tab **Session Manager** → **Connect**. You get a
shell as `ssm-user`. Switch to the service user:

```bash
sudo su - ec2-user
```

(On Ubuntu-based templates the user is `ubuntu`; replace `ec2-user` with `ubuntu` everywhere
below, including in `deploy/roostoo-bot.service`.)

## 3. Install git and Python, clone, create the venv

Amazon Linux 2023:

```bash
sudo dnf install -y git python3 python3-pip
```

Ubuntu:

```bash
sudo apt-get update && sudo apt-get install -y git python3 python3-venv python3-pip
```

Then:

```bash
cd ~
git clone https://github.com/navneet-23/roostoo-bot.git
cd roostoo-bot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q tests
```

All tests must pass before continuing.

## 4. Create .env with the COMPETITION key

```bash
nano .env
```

Paste exactly three lines, then Ctrl+O, Enter, Ctrl+X:

```
ROOSTOO_API_KEY=<competition api key>
ROOSTOO_SECRET_KEY=<competition secret key>
MODE=live
```

Lock it down:

```bash
chmod 600 .env
```

## 5. Check that Binance and Roostoo are reachable from the instance

```bash
curl -s -m 10 "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=1" | head -c 200; echo
curl -s -m 10 "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=1" | head -c 200; echo
curl -s -m 10 https://mock-api.roostoo.com/v3/serverTime; echo
```

Each should print JSON. If the first Binance host is blocked the bot falls back to the second
automatically; if both fail it falls back to its own Roostoo price store and holds positions.

Optional dry run for one cycle (sends nothing; uses the live key read-only):

```bash
MODE=dry_run timeout 120 .venv/bin/python -m bot.main; tail -3 logs/cycles.csv
```

## 6. Install the systemd service

```bash
sudo cp deploy/roostoo-bot.service /etc/systemd/system/roostoo-bot.service
sudo systemctl daemon-reload
sudo systemctl enable roostoo-bot
sudo systemctl start roostoo-bot
sudo systemctl status roostoo-bot --no-pager
```

`Restart=always` restarts the process after any crash and `enable` starts it on boot. The bot
re-reads balances and short positions from the API on every start, and persists the
drawdown-stop state in `state/state.json`, so a restart never resets anything.

## 7. Watch it

```bash
sudo journalctl -u roostoo-bot -f              # live process log
tail -f logs/bot.log                           # same, from the rotating file
tail -5 logs/cycles.csv                        # one row per 4h cycle: equity, signals, weights
tail -5 logs/orders.csv                        # every order with the full API response
tail -3 logs/heartbeat.csv                     # every 15 minutes
cat state/state.json                           # peak, cooldown, size multiplier
```

The first cycle runs immediately on start (the last closed 4h bar is processed), then about
one minute after every 4h close UTC: 00:01, 04:01, 08:01, 12:01, 16:01, 20:01.

## 8. Updating the bot

Only committed code ever changes behaviour:

```bash
cd ~/roostoo-bot
git pull
.venv/bin/pip install -r requirements.txt     # only if requirements changed
.venv/bin/python -m pytest -q tests
sudo systemctl restart roostoo-bot
sudo journalctl -u roostoo-bot -n 50 --no-pager
```

## 9. Pre-flight on a TEST key (laptop, never the competition key)

```bash
cp .env.example .env            # fill in the TEST key, MODE=dry_run
python -m pytest -q tests
python -m scripts.endpoint_check            # read-only endpoints
python -m scripts.endpoint_check --trade    # $15 buy/sell, $10 short open/close; writes docs/ENDPOINT_CHECK.md
MODE=live timeout 600 python -m bot.main    # a short live run on the TEST key
```
