# 申请进度助手 · 试用版

给一家机构真实试用一周的版本：顾问端（今天 / 录入 / 学生）、老板端（看板 / 留痕）、设置（账号、学生、密码）。
规则和演示版一致；数据存在服务器上的一个 SQLite 文件里。

## 和演示版相比多了什么

- **登录**：老板账号由我们在服务器上开；老板在「设置」里给顾问开账号、重置密码、停用账号。
- **加一所学校**：截止日从日期库带出，只是预填。专业截止更早的，顾问直接改，并写一句原因，记进留痕。
  会生成 6 件事：文书终稿、送分、成绩单、推荐信、申请费、递交。每一件的日期、负责人都能改，不需要的取消勾选，也能再加一项。
  默认提前几天在 `static/config.js` 的 `backplan` 里改。
- **滚动录取**：学校没有截止日时，顾问填和学生商定的计划递交日，按这个日期倒排。
- **库里没有的学校**：顾问自己填轮次、截止日、来源，勾上「记住」后本机构所有顾问下次都能直接选（产品记忆）。
- **任何事项的截止日都能改**：在学生页点一行，改日期并写原因。也能在那里标完成、记家长已回复、删除。
- **撤销**：30 分钟内自己的操作可以撤销。留痕不会删，只标「已撤销」，老板看得到。
- **录入**：手动添加；配置了 AI 密钥后可以贴笔记或微信聊天让 AI 整理。AI 给的每一条都必须带原文里的原话，程序核对原话确实在原文里，对不上的丢掉；顾问确认后才写入。原文不保存。
- **报名学校**：学生页先按地区（美国、英国、香港、澳洲、加拿大等）列出这个学生报了哪些学校，点一所学校再看它的事项。日期库里没有的学校照样能加，顾问自己填地区、轮次和截止日。
- **顾问端四个页签**：总览（和老板看板同一种视图，只看自己的学生）、待办、录入留痕、学生。状态统一叫 紧急 / 临期 / 正常。
- **录入留痕**：笔记、微信聊天、家长回复、截图都贴在同一个框里，AI 找出新事项、家长回复、已办完的事，顾问确认后写入并留痕；右边是这个学生的留痕。也可以手动加事项、手动记一条家长回复。提示词见 `提示词/信息整理提示词.md`。
- **话术**：约定、催办、进度回复各有几种说法，可以点「换一种说法」；不带顾问名字，不用特殊符号。在 `static/config.js` 里改。
- **图片识别**：录入页可以加最多 4 张图片（微信截图、学校邮件截图、笔记照片），也能直接粘贴截图。AI 先把图里的字转写出来，再整理成事项；原话核对的是这份转写，所以页面会把转写给顾问对照图片看。图片不保存。
- **导出**：老板可以在「留痕」页导出全部事项和留痕（CSV，Excel 能打开）。

## 只存最少的信息

存：学生称呼（可以用代号）、家长称呼、事项、日期、进度、留痕。
不存：身份证、电话、成绩单、聊天原文。AI 整理时原文会发给 AI 服务商（默认 DeepSeek），整理完不保存。

## 本地运行

```sh
cd app
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py new-agency          # 按提示建机构和老板账号
SECURE_COOKIE=0 .venv/bin/uvicorn server:app --port 8000
# 打开 http://127.0.0.1:8000
```

测试：`.venv/bin/pip install pytest && .venv/bin/python -m pytest tests -q`

## 部署到香港云服务器（约 30 到 60 元一个月）

需要：一台香港轻量服务器（腾讯云或阿里云，Ubuntu 22.04 或 24.04，1 核 1G 就够），一个域名（解析到服务器 IP）。香港服务器不需要备案。

```sh
# 1. 装软件
sudo apt update && sudo apt install -y python3-venv git sqlite3 caddy
sudo useradd -m -d /srv app && sudo mkdir -p /srv/data && sudo chown -R app /srv

# 2. 拉代码、装依赖
sudo -u app git clone https://github.com/3VEN5/20w.git /srv/20w
cd /srv/20w/app && sudo -u app python3 -m venv .venv && sudo -u app .venv/bin/pip install -r requirements.txt

# 3. 配置
sudo cp deploy/app.env.example /srv/app.env && sudo chmod 600 /srv/app.env && sudo chown app /srv/app.env
sudo nano /srv/app.env                          # 需要 AI 整理就填 AI_API_KEY

# 4. 建机构和老板账号
sudo -u app sh -c 'set -a; . /srv/app.env; .venv/bin/python manage.py new-agency'

# 5. 启动服务
sudo cp deploy/app.service /etc/systemd/system/ && sudo systemctl enable --now app

# 6. HTTPS：把 deploy/Caddyfile 里的域名改成你们的，再
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy

# 7. 每天备份数据库、每天更新日期库（爬虫每周一更新 GitHub 上的数据）
sudo crontab -u app -e
#   0 3 * * * /srv/20w/app/deploy/backup.sh
#   30 9 * * * cd /srv/20w && git pull -q
```

更新代码：`cd /srv/20w && sudo -u app git pull && sudo systemctl restart app`

## 试用前要定的事

- 域名和服务器由谁的名义购买、谁付费。
- 要不要开 AI 整理：需要一个 DeepSeek（或通义千问）账号和 API 密钥，按用量付费，一周试用通常几块钱。

## 接入 AI（服务器版）

在 `/srv/app.env` 里填，改完 `sudo systemctl restart app`：

| 功能 | 填什么 | 去哪里拿 |
|---|---|---|
| 文字整理 | `AI_API_KEY=sk-...`（默认用 DeepSeek，模型 deepseek-chat） | platform.deepseek.com 注册、充值、建 API key |
| 图片识别 | `AI_VISION_MODEL=qwen-vl-max`，`AI_VISION_API_KEY=sk-...` | 阿里云百炼（通义千问）开通、建 API key。DeepSeek 不能看图 |

只想用一家：把 `AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`、`AI_MODEL=qwen-plus`、`AI_API_KEY` 都填通义千问的，图片再填 `AI_VISION_MODEL=qwen-vl-max` 就行（`AI_VISION_API_KEY` 不填会用 `AI_API_KEY`）。
密钥只放在服务器的 `/srv/app.env`，不要发到群里或提交到 GitHub。
- 给机构的数据说明：我们存什么、不存什么、试用结束后怎么删除（`manage.py` 之外，直接删 `/srv/data/app.db` 和备份）。
