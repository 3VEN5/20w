#!/bin/sh
# 每天备份一次数据库，保留 30 天。用 cron 运行：0 3 * * * /srv/20w/app/deploy/backup.sh
set -e
mkdir -p /srv/backup
sqlite3 /srv/data/app.db ".backup '/srv/backup/app-$(date +%F).db'"
find /srv/backup -name 'app-*.db' -mtime +30 -delete
