# 20w

| 文件夹 | 内容 |
|---|---|
| `app/` | 申请进度助手。`static/` 是服务器版页面，`artifact/` 是 Claude 托管的可用版，说明见里面的 README |
| `爬虫/` | 学校申请截止日期爬虫，每周一自动运行。人工核实的日期在 `manual_deadlines.csv`，说明见里面的 README |
| `提示词/` | 给 AI 的提示词。接 DeepSeek、通义千问等模型时照这里的内容用 |

发给家长的话术不是提示词，在 `app/static/config.js` 的 `templates` 里改。
