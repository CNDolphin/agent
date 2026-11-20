-- 启用 DeepSeek 对话模型并设置默认价格(单位:积分/百万 token)。
-- 仅在种子状态(未启用且价格全为 0)时生效,避免覆盖管理员后续调价或停用。
UPDATE model_prices
SET in_hit_per_m = 100,
    in_miss_per_m = 200,
    out_per_m = 800,
    enabled = true,
    version = version + 1
WHERE model = 'deepseek-flash'
  AND enabled = false
  AND in_hit_per_m = 0
  AND in_miss_per_m = 0
  AND out_per_m = 0;
