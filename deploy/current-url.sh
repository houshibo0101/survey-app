#!/bin/bash
# 输出调查问卷系统当前的公网地址（cpolar 隧道）
LOG=/opt/survey-app/cpolar-survey.log
URL=$(grep -a -o -E "https://[a-zA-Z0-9.-]+\.cpolar\.[a-z]+" "$LOG" 2>/dev/null | tail -1)
if [ -z "$URL" ]; then
  echo "尚未获取到公网地址，请检查 cpolar-survey 服务："
  echo "  systemctl status cpolar-survey"
  exit 1
fi
echo "公网地址：$URL"
echo "局域网地址：http://192.168.9.108/survey/"
