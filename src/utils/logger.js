/**
 * 日志工具模块
 * 统一管理所有日志输出
 */

const fs = require('fs');
const path = require('path');

class Logger {
  constructor() {
    this.logDir = path.join(__dirname, '../../logs');
    this.ensureLogDir();
  }

  /**
   * 确保日志目录存在
   */
  ensureLogDir() {
    if (!fs.existsSync(this.logDir)) {
      fs.mkdirSync(this.logDir, { recursive: true });
    }
  }

  /**
   * 格式化时间戳
   */
  getTimestamp() {
    const now = new Date();
    return now.toISOString();
  }

  /**
   * 写入日志文件
   */
  writeToFile(level, message, data) {
    const logFile = path.join(
      this.logDir,
      `${new Date().toISOString().split('T')[0]}.log`
    );

    const logEntry = {
      timestamp: this.getTimestamp(),
      level,
      message,
      data: data || undefined,
    };

    const logLine = JSON.stringify(logEntry) + '\n';

    try {
      fs.appendFileSync(logFile, logLine);
    } catch (error) {
      console.error('[Logger] 写入日志文件失败:', error);
    }
  }

  /**
   * 格式化数据对象
   */
  formatData(data) {
    if (!data) return '';
    try {
      return typeof data === 'object'
        ? JSON.stringify(data, null, 2)
        : String(data);
    } catch (error) {
      return String(data);
    }
  }

  /**
   * Info级别日志
   */
  info(message, data) {
    console.log(`[INFO] ${this.getTimestamp()} ${message}`);
    if (data) {
      console.log(this.formatData(data));
    }
    this.writeToFile('INFO', message, data);
  }

  /**
   * Warn级别日志
   */
  warn(message, data) {
    console.warn(`[WARN] ${this.getTimestamp()} ${message}`);
    if (data) {
      console.warn(this.formatData(data));
    }
    this.writeToFile('WARN', message, data);
  }

  /**
   * Error级别日志
   */
  error(message, data) {
    console.error(`[ERROR] ${this.getTimestamp()} ${message}`);
    if (data) {
      console.error(this.formatData(data));
    }
    this.writeToFile('ERROR', message, data);
  }

  /**
   * Debug级别日志
   */
  debug(message, data) {
    if (process.env.NODE_ENV !== 'production') {
      console.log(`[DEBUG] ${this.getTimestamp()} ${message}`);
      if (data) {
        console.log(this.formatData(data));
      }
    }
    this.writeToFile('DEBUG', message, data);
  }

  /**
   * Success级别日志
   */
  success(message, data) {
    console.log(`[SUCCESS] ${this.getTimestamp()} ${message}`);
    if (data) {
      console.log(this.formatData(data));
    }
    this.writeToFile('SUCCESS', message, data);
  }
}

module.exports = new Logger();
