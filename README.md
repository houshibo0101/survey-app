# 调查问卷系统

[![CI](https://github.com/houshibo0101/survey-app/actions/workflows/ci.yml/badge.svg)](https://github.com/houshibo0101/survey-app/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/houshibo0101/survey-app/blob/main/LICENSE)

一套可直接部署的问卷调研系统：注册登录、按人授权查看结果、为指定用户伪装作答选项、接入 AI 按提示词批量出题。

- 后端：Python 3 标准库（无需安装任何第三方依赖）
- 前端：原生 HTML/CSS/JS 单页应用（无需构建）
- 数据：SQLite（单文件，便于备份）
- 部署：systemd + nginx 反向代理，cpolar 内网穿透

## 访问地址

| 入口 | 地址 |
| --- | --- |
| 公网（cpolar） | https://<你的 cpolar 域名> |
| 局域网 | http://<服务器内网 IP>/survey/ |
| 本机后端 | http://127.0.0.1:8090/api/health |

公网地址由 `cpolar-survey` 服务维护，随时可运行 `/opt/survey-app/current-url.sh` 查看当前地址。

## 账号

- 初始管理员：`admin`，密码见服务器 `/opt/survey-app/ADMIN_PASSWORD.txt`（安装时随机生成，仅 root/mc 可读）。
- 普通参与者可自行注册，也可以由管理员在「用户管理」中创建。
- 登录后右上角「修改密码」可自助改密；管理员还能重置任意用户密码。

## 功能

### 1. 账号与登录
注册、登录、退出、修改密码；会话使用 HMAC 签名 Cookie（7 天），口令使用 PBKDF2-SHA256（26 万次迭代）加盐存储。

### 2. 问卷
管理员在「问卷管理」中创建问卷、编辑题目：单选、多选、填空、量表（1-5）。可设置必答、开关问卷、删除问卷。

### 3. 结果可见性（谁可以看谁的结果）
「结果可见性」页是一张矩阵：行＝被查看者，列＝查看者，勾选即授权。
- 适用范围可选「全部问卷」或某一份问卷。
- 管理员始终可以查看全部答卷与统计（含选项分布、文字回答）。
- 普通用户只能看到：自己的答卷 + 管理员授权给他的成员答卷；勾选授权后立即生效。

### 4. 虚假选项（伪装作答界面）
「虚假选项」页：选择问卷 + 受访者，即可为某道选择题替换该用户作答时看到的选项（例如把真实搭档姓名换成虚构姓名）。
- 只影响这位用户在作答界面看到的内容，真实选项不会出现在他的页面上。
- 提交后按「他实际看到的内容」保存，管理员在统计中能看到这些伪造选项的计数。
- 留空保存或点「恢复真实选项」即可取消伪装。

### 5. AI 出题
「系统设置」中填写任意 OpenAI 兼容接口后，「AI 出题」页可用：
- 接口地址（如 `https://api.deepseek.com/v1`）、模型（如 `deepseek-chat`）、API Key、温度。
- 提示词 + 题目数量 + 题型（可多选：单选/多选/填空/量表，选中多种时每种至少 1 道、自动平均分配）→ 一键生成，预览勾选后批量加入指定问卷。
- 提示词可保存为模板，重复使用；系统提示词可自定义（默认已内置「问卷设计专家 + 严格 JSON 输出」约束）。
- 未配置 Key 时接口会返回明确提示，不影响系统其他功能。
- 「测试连接」按钮会用当前表单内容发一条极短请求，直接显示成功或服务商返回的原始错误。

常见服务商填写方式：

| 服务商 | 接口地址 | 模型示例 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 火山方舟 | `https://ark.cn-beijing.volces.com/api/v3` | 控制台已开通的模型名，或推理接入点 ID `ep-...` |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |

排错提示：
- `InvalidEndpoint.ClosedEndpoint` / `InvalidEndpointOrModel.NotFound`：方舟侧没有开通该模型或模型名写错，去「模型广场」开通后用模型名或 `ep-` 接入点 ID。
- `HTTP 401`：Key 无效或过期。
- 地址多写了 `/chat/completions` 或 `/responses` 也能用，系统会自动去掉这些后缀。

## 运维

```bash
# 应用状态 / 重启 / 日志
systemctl status survey-app
systemctl restart survey-app
journalctl -u survey-app -n 100 --no-pager

# 公网隧道状态 / 重启 / 当前地址
systemctl status cpolar-survey
systemctl restart cpolar-survey
/opt/survey-app/current-url.sh
grep -a -o -E "https://[a-zA-Z0-9.-]+\.cpolar\.[a-z]+" /opt/survey-app/cpolar-survey.log | tail -1

# 修改端口等环境变量
vi /opt/survey-app/.env && systemctl restart survey-app

# 备份数据（全部业务数据就在一个文件里）
cp /opt/survey-app/data/survey.db /path/to/backup/survey-$(date +%F).db

# 重新部署代码
scp -r 本地目录/* mc@<服务器 IP>:/tmp/survey-install/ && \
  ssh mc@<服务器 IP> "echo 密码 | sudo -S -p '' bash /tmp/survey-install/deploy/install.sh"
```

### 网络结构

```
公网 https://<你的 cpolar 域名>
        │  (cpolar 隧道: cpolar-survey.service → 127.0.0.1:8090)
        ▼
   127.0.0.1:8090  survey-app.service (Python)
        ▲
        │  /survey/ 反向代理（nginx :80）
   局域网 http://<服务器内网 IP>/survey/
```

## 目录结构

```
/opt/survey-app/
├── server.py          # HTTP 服务、路由、业务逻辑
├── db.py              # SQLite 数据层、口令散列、会话令牌
├── ai.py              # OpenAI 兼容接口调用与题目 JSON 解析
├── static/            # 前端（index.html / app.js / style.css）
├── deploy/            # systemd 单元、nginx 片段、安装脚本
├── data/survey.db     # 业务数据（自动创建）
├── .env               # 端口、数据目录、初始管理员密码
└── ADMIN_PASSWORD.txt # 初始管理员密码
```

## 手机端适配

界面已做响应式处理，手机浏览器打开即自动适配：

- 桌面端保留顶部导航；宽度 ≤720px 时切换为**底部导航栏**（问卷 / 管理 / 改密 / 退出），并适配 iPhone 刘海屏与手势区安全距离。
- 列表与表格在手机上自动**卡片化**：每条答卷、每个用户、每道题目独立成卡，左侧标签 + 右侧内容，不再横向挤压。
- 表单单列排布，输入框字号 16px（避免 iOS 聚焦自动放大），按钮高度 ≥42px 便于点击。
- 结果统计的条形图、可见性矩阵、AI 生成列表都做了窄屏压缩；矩阵保留横向滑动 + 首列吸附。
- 弹窗在手机上改为底部抽屉样式。

刷新页面（必要时 Ctrl+F5）即可看到效果，也可以直接用手机访问 https://<你的 cpolar 域名>。

## 安全建议

1. 首次登录后立即修改 `admin` 密码。
2. `SURVEY_ADMIN_PASSWORD` 只在首次初始化时使用，改密后可从 `.env` 删除。
3. 公网地址由 cpolar 隧道提供（`cpolar-survey` 服务）；更换 cpolar 账号或隧道配置后地址会变化，运行 `/opt/survey-app/current-url.sh` 即可获取最新地址。
4. 系统未实现登录失败锁定，若暴露在公网建议在 nginx 层增加访问频率限制。

## 文档

更详细的说明见 [Wiki](https://github.com/houshibo0101/survey-app/wiki)：

- [快速开始](https://github.com/houshibo0101/survey-app/wiki/%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B)
- [功能说明](https://github.com/houshibo0101/survey-app/wiki/%E5%8A%9F%E8%83%BD%E8%AF%B4%E6%98%8E)
- [AI 配置与提示词](https://github.com/houshibo0101/survey-app/wiki/AI-%E9%85%8D%E7%BD%AE)
- [部署指南](https://github.com/houshibo0101/survey-app/wiki/%E9%83%A8%E7%BD%B2%E6%8C%87%E5%8D%97)
- [数据与备份](https://github.com/houshibo0101/survey-app/wiki/%E6%95%B0%E6%8D%AE%E4%B8%8E%E5%A4%87%E4%BB%BD)
- [常见问题](https://github.com/houshibo0101/survey-app/wiki/%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98)
