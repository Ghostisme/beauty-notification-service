const EventEmitter = require('events');

/**
 * 消息队列
 * 负责管理待推送的消息，控制推送频率，防止超过企微限制
 */
class MessageQueue extends EventEmitter {
  constructor(logger) {
    super();
    this.logger = logger;
    this.queue = [];
    this.processing = false;
    this.stats = {
      total: 0,
      success: 0,
      failed: 0,
      startTime: Date.now()
    };

    // 推送间隔（毫秒），默认3秒，企微限制每分钟20条
    this.messageDelay = parseInt(process.env.MESSAGE_DELAY) || 3000;
  }

  /**
   * 消息入队
   */
  async enqueue(task) {
    this.queue.push(task);
    this.stats.total++;
    this.emit('enqueued', task);

    this.logger.debug({
      storeId: task.storeId,
      queueSize: this.queue.length
    }, '消息已入队');
  }

  /**
   * 获取队列大小
   */
  size() {
    return this.queue.length;
  }

  /**
   * 获取统计信息
   */
  getStats() {
    const runTime = Date.now() - this.stats.startTime;
    const successRate = this.stats.total > 0
      ? ((this.stats.success / this.stats.total) * 100).toFixed(2)
      : '0.00';

    return {
      pending: this.queue.length,
      total: this.stats.total,
      success: this.stats.success,
      failed: this.stats.failed,
      successRate: successRate + '%',
      runTime: Math.floor(runTime / 1000) + 's',
      avgSpeed: this.stats.success > 0
        ? (this.stats.success / (runTime / 1000 / 60)).toFixed(2) + ' msg/min'
        : 'N/A'
    };
  }

  /**
   * 开始处理队列
   */
  startProcessing(handler) {
    if (this.processing) {
      this.logger.warn('队列处理已在运行');
      return;
    }

    this.processing = true;
    this.logger.info('队列处理已启动');

    this._process(handler).catch(error => {
      this.logger.error({ error: error.message }, '队列处理异常');
    });
  }

  /**
   * 停止处理
   */
  stop() {
    this.processing = false;
    this.logger.info('队列处理已停止');
  }

  /**
   * 处理循环
   */
  async _process(handler) {
    while (this.processing) {
      // 队列为空时等待
      if (this.queue.length === 0) {
        await this._sleep(100);
        continue;
      }

      const task = this.queue.shift();
      const startTime = Date.now();

      try {
        await handler(task);

        this.stats.success++;
        this.emit('success', task);

        this.logger.debug({
          storeId: task.storeId,
          orderId: task.orderId,
          duration: Date.now() - startTime
        }, '消息处理成功');

      } catch (error) {
        this.stats.failed++;
        this.emit('failed', { task, error });

        this.logger.error({
          storeId: task.storeId,
          orderId: task.orderId,
          error: error.message
        }, '消息处理失败');

        // 失败后重试一次（可选）
        if (!task.retried) {
          this.logger.info({ orderId: task.orderId }, '重试推送');
          task.retried = true;
          this.queue.push(task);
        }
      }

      // 限流：每条消息间隔指定时间
      await this._sleep(this.messageDelay);
    }

    this.logger.info('队列处理循环已退出');
  }

  /**
   * 排空队列（优雅退出时使用）
   */
  async drain(timeout = 60000) {
    const start = Date.now();

    this.logger.info({
      remaining: this.queue.length,
      timeout: timeout / 1000 + 's'
    }, '等待队列排空...');

    while (this.queue.length > 0) {
      if (Date.now() - start > timeout) {
        this.logger.warn({
          remaining: this.queue.length
        }, '排空超时，放弃剩余消息');
        break;
      }
      await this._sleep(100);
    }

    this.stop();
    this.logger.info('队列已排空');
  }

  /**
   * 睡眠函数
   */
  _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

module.exports = { MessageQueue };
