# 可用版（在 Claude 网页里运行，不用买服务器）

和 `app/static` 的服务器版是同一套页面和规则，区别只在数据层 `store.js`：

- 数据存在 Claude 网页自带的数据库（`claude.use("db")`），用 Claude 账号识别成员，不用另设密码。
- AI 整理用网页自带的 Claude（`sample`），不用买 API 密钥；程序同样核对每条原话确实在原文里。
- 录入可以语音输入（`dictation`，Chrome 和 Claude 桌面版）。
- 第一次打开时填称呼。页面所有者是老板，其他人默认是顾问，老板可在「设置」里改。
- 同事要能写数据，需要在分享里设为"可编辑"（Contributor）。

发布：把 `index.html`、`store.js`、`config.js` 和 `爬虫/data/deadlines_web.js`（改名为 `deadlines.js`）一起发布。
数据库规则：`members` 每人只能写自己的那条（老板能改所有人），`app/settings` 只有老板能写，其余默认。

已知限制：留痕防篡改只在服务器版里由后台保证；这里有编辑权限的人在技术上可以改数据库。
