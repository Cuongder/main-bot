# Main Bot

Bot giao dịch Binance Futures demo bằng Python, có:

- giao dịch live `24/7`
- backtest
- Telegram alert và command
- preflight check trước khi đưa lên VPS

## Ubuntu VPS

### 1. Cài hệ thống

```bash
sudo apt update
sudo apt install -y git curl python3 python3-venv python3-pip
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2
```

### 2. Clone repo

```bash
git clone https://github.com/Cuongder/main-bot.git
cd main-bot
```

### 3. Tạo môi trường Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Tạo file môi trường

```bash
cp .env.example .env.local
nano .env.local
```

Điền:

- `BINANCE_API_DEMO`
- `BINANCE_SECRET_DEMO`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `URL_ENPOINT`
- `API_ENPOINT`
- `MODEL`

### 5. Chạy preflight trước khi bật bot

Kiểm tra môi trường và kết nối:

```bash
source .venv/bin/activate
python preflight_check.py --smoke-order
```

Nếu kết quả trả về `ready: true`, chạy thêm smoke test lệnh thật với size nhỏ:

```bash
python preflight_check.py --live-order-smoke --symbol ETH/USDT --amount 0.01
```

Chỉ khi cả hai bước đều ổn mới nên bật bot `24/7`.

### 6. Chạy bot với PM2

Repo đã có sẵn file `ecosystem.config.js`.

Khởi động:

```bash
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

Sau khi chạy `pm2 startup`, PM2 sẽ in ra một lệnh `sudo ...`, bạn copy và chạy đúng lệnh đó một lần.

## Lệnh vận hành

### PM2

```bash
pm2 status
pm2 logs main-bot
pm2 restart main-bot
pm2 stop main-bot
pm2 delete main-bot
```

### App

```bash
python main.py trade
python main.py backtest
python preflight_check.py --smoke-order
python preflight_check.py --live-order-smoke --symbol ETH/USDT --amount 0.01
```

## Telegram Commands

- `/healthcheck`
- `/balance`
- `/position`
- `/close`

## Log và file quan trọng

- PM2 stdout: `data/pm2-out.log`
- PM2 stderr: `data/pm2-error.log`
- app log: `data/bot.log`
- trade log: `data/trades.json`

## Cập nhật bot trên VPS

```bash
cd ~/main-bot
git pull
source .venv/bin/activate
pip install -r requirements.txt
python preflight_check.py --smoke-order
pm2 restart main-bot
pm2 save
```

Nếu thay đổi lớn liên quan order routing, Telegram, hoặc exchange, nên chạy lại:

```bash
python preflight_check.py --live-order-smoke --symbol ETH/USDT --amount 0.01
```

## Gợi ý an toàn

- Dùng tài khoản Binance demo, không dùng key tài khoản thật.
- Luôn chạy `preflight_check.py` sau khi sửa `.env.local` hoặc đổi VPS.
- Nếu Telegram không phản hồi, kiểm tra firewall hoặc outbound HTTPS tới `api.telegram.org`.
- Nếu Binance demo không phản hồi, chạy lại preflight trước khi bật PM2.

## Tài liệu thêm

- Runbook chi tiết: `docs/vps-demo-runbook.md`
