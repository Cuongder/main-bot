module.exports = {
  apps: [
    {
      name: "main-bot",
      cwd: __dirname,
      script: "main.py",
      args: "trade",
      interpreter: "./.venv/bin/python3",
      instances: 1,
      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 5000,
      env: {
        PYTHONUNBUFFERED: "1",
      },
      error_file: "./data/pm2-error.log",
      out_file: "./data/pm2-out.log",
      merge_logs: true,
      time: true,
    },
  ],
};
