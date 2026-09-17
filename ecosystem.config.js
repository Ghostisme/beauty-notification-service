/**
 * PM2 配置文件
 * 用于生产环境进程管理
 */

module.exports = {
  apps: [{
    name: 'beauty-notification',
    script: 'src/server.js',

    // 实例配置
    instances: 1,
    exec_mode: 'fork',

    // 环境变量
    env: {
      NODE_ENV: 'production',
      PORT: 3000
    },

    // 自动重启配置
    autorestart: true,
    watch: false,
    max_memory_restart: '500M',

    // 日志配置
    error_file: 'logs/pm2-error.log',
    out_file: 'logs/pm2-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    merge_logs: true,

    // 重启策略
    min_uptime: '10s',
    max_restarts: 10,

    // 时间配置
    time: true,

    // 优雅退出
    kill_timeout: 5000,
    wait_ready: true,
    listen_timeout: 10000
  }]
};
