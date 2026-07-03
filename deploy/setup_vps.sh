#!/bin/bash
# Run this script on VPS after SSH login.
# Usage: bash setup_vps.sh
set -e

REPO="https://github.com/pritulai/youtube-analyses.git"
DIR="$HOME/youtube-analyses"
USER=$(whoami)

echo "=== 1. Диагностика ==="
lsb_release -a 2>/dev/null || cat /etc/os-release
python3 --version && which python3
echo ""

echo "=== 2. Проверка n8n (не трогаем!) ==="
docker ps 2>/dev/null | grep -i n8n || echo "(Docker не найден или n8n не в Docker)"
systemctl list-units --type=service --state=running 2>/dev/null | grep -E "n8n|node" || echo "(n8n не найден через systemd)"
ss -tlnp | grep -E "80|443|5678" || echo "(Порты 80/443/5678 свободны или netstat недоступен)"
echo ""

echo "=== 3. Клонируем репозиторий ==="
if [ -d "$DIR" ]; then
    echo "Директория уже есть — делаем git pull"
    cd "$DIR" && git pull
else
    git clone "$REPO" "$DIR"
    cd "$DIR"
fi
echo ""

echo "=== 4. Python venv ==="
cd "$DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "Пакеты установлены."
echo ""

echo "=== 5. Проверка .env ==="
if [ ! -f "$DIR/.env" ]; then
    echo "[WARN] .env не найден! Скопируй его с локальной машины:"
    echo "  scp your-local-path/.env $USER@$(hostname -I | awk '{print $1}'):$DIR/.env"
    echo "  Не забудь: убрать HTTPS_PROXY, добавить FORCE_SKIP_NOTEBOOK=true"
else
    echo ".env найден."
fi
echo ""

echo "=== 6. Проверка token.json ==="
if [ ! -f "$DIR/token.json" ]; then
    echo "[WARN] token.json не найден! Скопируй с локальной машины:"
    echo "  scp your-local-path/token.json $USER@$(hostname -I | awk '{print $1}'):$DIR/token.json"
else
    echo "token.json найден."
fi
echo ""

echo "=== 7. Настройка systemd-сервиса ==="
SERVICE_SRC="$DIR/deploy/ytbot.service"
SERVICE_DST="/etc/systemd/system/ytbot.service"

# Подставляем реального пользователя
sed "s/YOUR_USER/$USER/g" "$SERVICE_SRC" | sudo tee "$SERVICE_DST" > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable ytbot
echo "Сервис ytbot зарегистрирован."
echo ""

echo "=== Готово! Запусти бота вручную для проверки: ==="
echo "  cd $DIR && source venv/bin/activate && python tools/bot_service.py"
echo ""
echo "После успешного теста запусти через systemd:"
echo "  sudo systemctl start ytbot && sudo systemctl status ytbot"
