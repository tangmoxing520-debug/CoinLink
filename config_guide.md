# 参数配置说明

## 主要可配置参数：

1. **监控分类**：修改 `CRYPTO_CATEGORIES` 添加/删除分类
2. **价格阈值**：调整 `PRICE_CHANGE_THRESHOLD` 设置暴涨阈值
3. **时间窗口**：修改 `time_windows` 设置监控的时间周期
4. **价格区间**：通过 `price_band_min/max` 过滤币种价格范围
5. **监控间隔**：调整 `MONITOR_INTERVAL` 设置检查频率

## 钉钉机器人创建：
1. 在钉钉群添加自定义机器人
2. 获取webhook地址和secret
3. 填入.env配置文件