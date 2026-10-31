#!/bin/bash
# 调查问卷系统 —— 服务器安装脚本（需要 root 运行）
# 用法：echo <sudo密码> | sudo -S -p '' bash /tmp/survey-install/install.sh
set -euo pipefail

APP_DIR=/opt/survey-app
SRC_DIR=/tmp/survey-install

echo "== 1/5 复制程序文件 =="
mkdir -p "$APP_DIR"
cp -a "$SRC_DIR/server.py" "$SRC_DIR/db.py" "$SRC_DIR/ai.py" "$SRC_DIR/README.md" "$APP_DIR/"
rm -rf "$APP_DIR/static" "$APP_DIR/deploy"
cp -a "$SRC_DIR/static" "$APP_DIR/static"
cp -a "$SRC_DIR/deploy" "$APP_DIR/deploy"
mkdir -p "$APP_DIR/data"
chown -R mc:mc "$APP_DIR"
chmod 700 "$APP_DIR/data"

echo "== 2/5 生成环境配置与初始管理员密码 =="
if [ ! -f "$APP_DIR/.env" ]; then
  ADMIN_PASSWORD=$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 16)
  cat > "$APP_DIR/.env" <<EOF
PORT=8090
HOST=127.0.0.1
SURVEY_DATA=$APP_DIR/data
SURVEY_ADMIN_PASSWORD=$ADMIN_PASSWORD
EOF
  echo "初始管理员密码：$ADMIN_PASSWORD" > "$APP_DIR/ADMIN_PASSWORD.txt"
  echo "已生成初始管理员密码：$ADMIN_PASSWORD"
else
  echo "已存在 .env，保留原有管理员密码"
fi
chmod 600 "$APP_DIR/.env" "$APP_DIR/ADMIN_PASSWORD.txt" 2>/dev/null || true

echo "== 3/5 安装 systemd 服务 =="
cp "$APP_DIR/deploy/survey-app.service" /etc/systemd/system/survey-app.service
systemctl daemon-reload
systemctl enable survey-app >/dev/null 2>&1 || true
systemctl restart survey-app

echo "== 4/5 配置 nginx 反向代理 =="
mkdir -p /etc/nginx/snippets
cp "$APP_DIR/deploy/nginx-survey.conf" /etc/nginx/snippets/survey.conf
if ! grep -q "snippets/survey.conf" /etc/nginx/sites-available/studyms; then
  cp /etc/nginx/sites-available/studyms "/etc/nginx/sites-available/studyms.bak.$(date +%Y%m%d%H%M%S)"
  python3 - <<'PY'
path = "/etc/nginx/sites-available/studyms"
text = open(path, encoding="utf-8").read()
marker = "    location / {"
index = text.find(marker)
if index == -1:
    raise SystemExit("未找到 location / 配置，需手动添加 include /etc/nginx/snippets/survey.conf;")
addition = "    include /etc/nginx/snippets/survey.conf;\n\n"
open(path, "w", encoding="utf-8").write(text[:index] + addition + text[index:])
PY
  echo "已在 studyms 站点中插入 survey 配置"
else
  echo "nginx 配置已存在，跳过"
fi
nginx -t
systemctl reload nginx

echo "== 4.5/5 配置 cpolar 隧道（8090 -> 公网） =="
if [ ! -f /home/mc/.cpolar-token.yml ] && [ -f /etc/cpolar/cpolar.yml ]; then
  cp /etc/cpolar/cpolar.yml /home/mc/.cpolar-token.yml
  chown mc:mc /home/mc/.cpolar-token.yml
  chmod 600 /home/mc/.cpolar-token.yml
fi
if [ -f /home/mc/.cpolar-token.yml ]; then
  cp "$APP_DIR/deploy/cpolar-survey.service" /etc/systemd/system/cpolar-survey.service
  cp "$APP_DIR/deploy/current-url.sh" "$APP_DIR/current-url.sh"
  chmod +x "$APP_DIR/current-url.sh"
  chown mc:mc "$APP_DIR/current-url.sh"
  systemctl daemon-reload
  systemctl enable cpolar-survey >/dev/null 2>&1 || true
  systemctl restart cpolar-survey
  echo "cpolar 隧道服务已启动"
else
  echo "未找到 cpolar 凭证，跳过公网隧道（可稍后手动配置）"
fi

echo "== 5/5 自检 =="
sleep 1
echo -n "后端健康检查: "
curl -s -m 5 http://127.0.0.1:8090/api/health || echo "失败"
echo
echo -n "本机 nginx /survey/ : "
curl -s -o /dev/null -w "%{http_code}\n" -m 5 http://127.0.0.1/survey/
echo -n "服务状态: "
systemctl is-active survey-app
sleep 4
echo -n "公网地址: "
su - mc -c 'bash /opt/survey-app/current-url.sh' 2>/dev/null | head -1 || echo "（稍后可运行 /opt/survey-app/current-url.sh 查看）"

echo "安装完成。"
