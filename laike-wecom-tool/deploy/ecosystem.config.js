const path = require('path');

const appDirectory = path.resolve(__dirname, '..');

module.exports = {
  apps: [{
    name: 'laike-wecom-tool',
    cwd: appDirectory,
    script: path.join(appDirectory, 'run.py'),
    interpreter: path.join(appDirectory, '.venv', 'bin', 'python'),
    args: '--host 127.0.0.1 --port 8790',
    exec_mode: 'fork',
    instances: 1,
    watch: false,
    autorestart: true,
    min_uptime: 10000,
    max_restarts: 5,
    restart_delay: 5000,
    kill_timeout: 90000,
    // PM2 restarts above this threshold; it is not a cgroup memory limit.
    max_memory_restart: '384M',
    time: true,
    env: {
      PYTHONUNBUFFERED: '1',
      PYTHONDONTWRITEBYTECODE: '1',
      COOKIE_SECURE: 'true',
      TOOL_DATA_DIR: path.join(appDirectory, 'data'),
      TZ: 'Asia/Shanghai',
    },
  }],
};
