#!/usr/bin/env bash
set -euo pipefail

readonly SERVICE_NAME=schoolringer
readonly SERVICE_USER=schoolringer
readonly SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

install_dir=/opt/schoolringer
data_dir=/var/lib/schoolringer
web_host=0.0.0.0
web_port=5000
media_port=8080
host_ip=""
open_firewall=false
host_ip_set=false
web_host_set=false
web_port_set=false
media_port_set=false

usage() {
  cat <<'EOF'
SchoolRinger Linux telepítő (Debian/Ubuntu, systemd)

Használat:
  sudo ./install.sh --host-ip VM_LAN_IP [kapcsolók]

Kapcsolók:
  --host-ip IP          A Google Home eszközök által elérhető VM LAN-cím
  --web-host IP         A webes felület bind címe (alapérték: 0.0.0.0)
  --web-port PORT       A webes felület portja (alapérték: 5000)
  --media-port PORT     A Cast média HTTP-portja (alapérték: 8080)
  --install-dir ÚTVONAL Az alkalmazás helye (alapérték: /opt/schoolringer)
  --data-dir ÚTVONAL    Az MP3-ak és adatok helye (alapérték: /var/lib/schoolringer)
  --open-firewall       UFW esetén megnyitja a szükséges helyi portokat
  -h, --help            Súgó
EOF
}

die() {
  printf 'Hiba: %s\n' "$*" >&2
  exit 1
}

need_value() {
  [[ $# -ge 2 && -n ${2:-} ]] || die "A(z) $1 kapcsolóhoz érték szükséges."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host-ip)
      need_value "$@"
      host_ip=$2
      host_ip_set=true
      shift 2
      ;;
    --web-host)
      need_value "$@"
      web_host=$2
      web_host_set=true
      shift 2
      ;;
    --web-port)
      need_value "$@"
      web_port=$2
      web_port_set=true
      shift 2
      ;;
    --media-port)
      need_value "$@"
      media_port=$2
      media_port_set=true
      shift 2
      ;;
    --install-dir)
      need_value "$@"
      install_dir=${2%/}
      shift 2
      ;;
    --data-dir)
      need_value "$@"
      data_dir=${2%/}
      shift 2
      ;;
    --open-firewall)
      open_firewall=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Ismeretlen kapcsoló: $1"
      ;;
  esac
done

[[ $EUID -eq 0 ]] || die "Futtasd root jogosultsággal: sudo ./install.sh ..."
command -v apt-get >/dev/null || die "Ez a telepítő Debian/Ubuntu apt rendszert támogat."
command -v systemctl >/dev/null || die "A telepítő systemd rendszert igényel."
[[ $install_dir =~ ^/[A-Za-z0-9._/-]+$ ]] || die "Érvénytelen install-dir: $install_dir"
[[ $data_dir =~ ^/[A-Za-z0-9._/-]+$ ]] || die "Érvénytelen data-dir: $data_dir"

if [[ -f /etc/default/schoolringer ]]; then
  # A fájl root tulajdonú, és a korábbi telepítő által írt változókat tartalmazza.
  source /etc/default/schoolringer
  [[ $host_ip_set == true ]] || host_ip=${SCHOOLRINGER_HOST_IP:-}
  [[ $web_host_set == true ]] || web_host=${SCHOOLRINGER_WEB_HOST:-$web_host}
  [[ $web_port_set == true ]] || web_port=${SCHOOLRINGER_WEB_PORT:-$web_port}
  [[ $media_port_set == true ]] || media_port=${SCHOOLRINGER_MEDIA_PORT:-$media_port}
fi

for port_spec in "web:$web_port" "média:$media_port"; do
  port=${port_spec#*:}
  [[ $port =~ ^[0-9]+$ ]] || die "A ${port_spec%%:*} port nem szám: $port"
  ((port >= 1 && port <= 65535)) || die "Érvénytelen ${port_spec%%:*} port: $port"
done
((web_port != media_port)) || die "A webes és média port nem lehet azonos."

printf '\n[1/7] Rendszercsomagok telepítése...\n'
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip avahi-daemon iproute2

if [[ -n $host_ip ]]; then
  python3 -c 'import ipaddress, sys; ipaddress.IPv4Address(sys.argv[1])' "$host_ip" \
    || die "Érvénytelen host-ip: $host_ip"
else
  printf 'Figyelmeztetés: nincs --host-ip megadva; több interfészes vagy NAT-os VM-en add meg a LAN-címet.\n' >&2
fi
python3 -c 'import ipaddress, sys; ipaddress.IPv4Address(sys.argv[1])' "$web_host" \
  || die "Érvénytelen web-host: $web_host"

printf '\n[2/7] Szolgáltatásfelhasználó létrehozása...\n'
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$data_dir" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

printf '\n[3/7] Alkalmazás telepítése: %s\n' "$install_dir"
if systemctl is-active --quiet "$SERVICE_NAME.service"; then
  systemctl stop "$SERVICE_NAME.service"
fi
install -d -o root -g root -m 0755 "$install_dir" "$install_dir/static" "$install_dir/templates" "$install_dir/scripts"
install -o root -g root -m 0644 "$SOURCE_DIR/scheduler_app.py" "$install_dir/scheduler_app.py"
install -o root -g root -m 0644 "$SOURCE_DIR/schoolringer.py" "$install_dir/schoolringer.py"
install -o root -g root -m 0644 "$SOURCE_DIR/requirements.txt" "$install_dir/requirements.txt"
install -o root -g root -m 0644 "$SOURCE_DIR/static/app.css" "$install_dir/static/app.css"
install -o root -g root -m 0644 "$SOURCE_DIR/static/app.js" "$install_dir/static/app.js"
install -o root -g root -m 0644 "$SOURCE_DIR/templates/index.html" "$install_dir/templates/index.html"
install -o root -g root -m 0755 "$SOURCE_DIR/scripts/run-service.sh" "$install_dir/scripts/run-service.sh"

printf '\n[4/7] Adatkönyvtár előkészítése: %s\n' "$data_dir"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$data_dir" "$data_dir/data" "$data_dir/media"
if [[ ! -f $data_dir/data/schedules.json ]]; then
  if [[ -f $SOURCE_DIR/data/schedules.json ]]; then
    install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/data/schedules.json" "$data_dir/data/schedules.json"
  else
    printf '[]\n' >"$data_dir/data/schedules.json"
    chown "$SERVICE_USER:$SERVICE_USER" "$data_dir/data/schedules.json"
    chmod 0640 "$data_dir/data/schedules.json"
  fi
fi
if [[ -f $SOURCE_DIR/data/settings.json && ! -f $data_dir/data/settings.json ]]; then
  install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/data/settings.json" "$data_dir/data/settings.json"
fi
shopt -s nullglob
for media_file in "$SOURCE_DIR"/media/*.mp3; do
  target_file="$data_dir/media/$(basename -- "$media_file")"
  if [[ ! -f $target_file ]]; then
    install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0640 "$media_file" "$target_file"
  fi
done
shopt -u nullglob

printf '\n[5/7] Python virtuális környezet és függőségek...\n'
python3 -m venv "$install_dir/.venv"
"$install_dir/.venv/bin/python" -m pip install --upgrade pip
"$install_dir/.venv/bin/python" -m pip install -r "$install_dir/requirements.txt"

printf '\n[6/7] systemd szolgáltatás beállítása...\n'
install -d -o root -g root -m 0755 /etc/default
config_tmp=$(mktemp)
unit_tmp=$(mktemp)
trap 'rm -f "$config_tmp" "$unit_tmp"' EXIT
cat >"$config_tmp" <<EOF
# SchoolRinger hálózati beállítások
SCHOOLRINGER_WEB_HOST=$web_host
SCHOOLRINGER_WEB_PORT=$web_port
SCHOOLRINGER_MEDIA_PORT=$media_port
SCHOOLRINGER_HOST_IP=$host_ip
EOF
install -o root -g "$SERVICE_USER" -m 0640 "$config_tmp" /etc/default/schoolringer

cat >"$unit_tmp" <<EOF
[Unit]
Description=SchoolRinger Google Cast scheduler
Wants=network-online.target avahi-daemon.service
After=network-online.target avahi-daemon.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$install_dir
Environment=SCHOOLRINGER_APP_DIR=$install_dir
Environment=SCHOOLRINGER_DATA_DIR=$data_dir
EnvironmentFile=-/etc/default/schoolringer
ExecStart=$install_dir/scripts/run-service.sh
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
install -o root -g root -m 0644 "$unit_tmp" "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable --now avahi-daemon.service

if [[ $open_firewall == true ]]; then
  if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
    ufw allow "$web_port/tcp"
    ufw allow "$media_port/tcp"
    ufw allow 5353/udp
  else
    printf 'Az UFW nincs telepítve vagy nem aktív; a tűzfalszabályok nem változtak.\n'
  fi
fi

printf '\n[7/7] SchoolRinger indítása...\n'
systemctl enable --now "$SERVICE_NAME.service"

printf '\nA telepítés elkészült.\n'
printf 'Webes felület: http://%s:%s\n' "${host_ip:-A_VM_IP_CÍME}" "$web_port"
printf 'Állapot: sudo systemctl status %s\n' "$SERVICE_NAME"
printf 'Napló:   sudo journalctl -u %s -f\n' "$SERVICE_NAME"
printf 'Beállítások: /etc/default/schoolringer\n'
printf 'MP3 könyvtár: %s/media\n' "$data_dir"
