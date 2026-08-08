# SchoolRinger

Helyi webes lejátszási rend Google Home speaker grouphoz. A felületen
tetszőleges számú heti időzítés hozható létre, napokkal, óra-perccel,
perc:másodperc formátumú lejátszási idővel, külön céleszközzel és a `media`
könyvtárban található MP3-fájlok egyikével.

## Feltételek

- Python 3.11 vagy újabb
- A futtató gép és a Google Home eszközök ugyanazon a helyi hálózaton legyenek
- A kliens tűzfala engedje az mDNS UDP 5353-at és a Python bejövő kapcsolatait
- A Google Home alkalmazásban már létezzen a megcélzott speaker group

> A GitHub Codespaces nem látja az otthoni hálózat Cast eszközeit. Az alkalmazást
> azon a helyi gépen kell futtatni, amely ugyanarra a Wi-Fi/LAN hálózatra
> csatlakozik, mint a Google Home hangszórók.

## Telepítés

### Automatikus Linux telepítés

Debian vagy Ubuntu `systemd`-s gépen add meg a VM hangszórók által elérhető
LAN-címét:

```bash
chmod +x install.sh
sudo ./install.sh \
  --host-ip 192.168.1.20 \
  --web-port 5000 \
  --media-port 8080 \
  --open-firewall
```

A telepítő létrehozza a virtuális környezetet, telepíti a Python- és
mDNS-függőségeket, majd `schoolringer.service` néven engedélyezi az automatikus
indulást. Ismételt futtatáskor frissíti a programot, de megtartja a mentett
időzítéseket és a már telepített MP3-fájlokat.

```bash
sudo systemctl status schoolringer
sudo journalctl -u schoolringer -f
sudo systemctl restart schoolringer
```

Telepítés után a program az `/opt/schoolringer`, a módosuló adatok és MP3-ak a
`/var/lib/schoolringer`, a hálózati beállítások pedig az
`/etc/default/schoolringer` alatt találhatók. Beállításmódosítás után indítsd újra
a szolgáltatást. A webes felület nem tartalmaz bejelentkezést, ezért csak
megbízható LAN-on vagy VPN-en tedd elérhetővé.

Új hangfájl telepítése után indítsd újra vagy frissítsd a weboldalt:

```bash
sudo install -o schoolringer -g schoolringer -m 0640 \
  sajat-zene.mp3 /var/lib/schoolringer/media/
```

### Kézi telepítés

```bash
cd "$HOME/céges/github/SchoolRinger"
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Az MP3-fájlokat tedd a projekt `media` könyvtárába. Az új fájlok a felület
következő frissítésekor automatikusan megjelennek a választóban.

## Konfigurációs felület

```bash
source .venv/bin/activate
python scheduler_app.py
```

Nyisd meg a böngészőben: [http://127.0.0.1:5000](http://127.0.0.1:5000)

A fejlécben az új időzítések alapértelmezett céleszköze választható ki az
automatikusan felderített speaker groupok és önálló Cast hangszórók közül.
Minden időzítéshez külön céleszköz állítható be; a korábban mentett, céleszköz
nélküli bejegyzések a fejlécben kiválasztott alapértelmezést használják. A
felületből létrehozható, szerkeszthető, kapcsolható és törölhető minden heti
időzítés. A **Próba** művelet azonnal elindítja a kiválasztott MP3-at a bejegyzés
céleszközén; aktív lejátszáskor az eseménypanelen megjelenő
**Leállítás** gomb megszakítja azt. A mentett időzítések a `data/schedules.json`, a
kiválasztott céleszköz pedig a `data/settings.json` fájlba kerül. Az időzítő csak
addig fut, amíg a `scheduler_app.py` folyamat fut.

Ha a gépnek több hálózati interfésze van, add meg a hangszórók által elérhető
LAN IP-címet és egy fix média portot:

```bash
python scheduler_app.py \
  --cast-host-ip 192.168.1.20 \
  --cast-media-port 8080
```

A webes felület másik porton a `--port 5001` kapcsolóval indítható. A
`--host 0.0.0.0` beállítás a helyi hálózat más eszközeiről is elérhetővé teszi
a konfigurációs felületet; ezt csak megbízható hálózaton használd.

### Linux virtuális gép

A VM hálózati adapterét lehetőleg **bridged** módra állítsd, hogy a VM saját,
a hangszórókkal azonos LAN-ból kapott IP-címmel rendelkezzen. A megfelelő címet
egy felderített hangszóró IP-címével ellenőrizheted:

```bash
ip -4 route get HANGSZÓRÓ_IP
```

A kimenet `src` utáni címét add át, és nyisd meg a média portot a VM tűzfalán:

```bash
sudo ufw allow 8080/tcp
python scheduler_app.py \
  --host 0.0.0.0 \
  --host-ip VM_LAN_IP \
  --cast-media-port 8080
```

NAT vagy host-only hálózati módban a VM címe rendszerint nem érhető el közvetlenül
a Google Home eszközökről. Ilyenkor bridged hálózat vagy a VM-platformon beállított
megfelelő porttovábbítás szükséges.

## Egyszeri lejátszás

A korábbi parancssori POC továbbra is használható:

```bash
python schoolringer.py --list
python schoolringer.py --group "Iskola"
python schoolringer.py --group "Iskola" --file media/masik.mp3
```

## Hibaelhárítás

Ha a csoport castol, de nincs hang, ellenőrizd a program által kiírt hangerőt
és média URL-t. A címben szereplő IP nem lehet `127.0.0.1`; a hangszóróknak is
el kell érniük. macOS-en engedélyezd a bejövő kapcsolatot a Python számára a
tűzfal párbeszédablakában, Windows esetén pedig a privát hálózatokon.

Telepített Linux szolgáltatásnál frissítés után futtasd újra a telepítőt; a
korábbi hálózati beállításokat, időzítéseket és MP3-fájlokat megtartja:

```bash
git pull
sudo ./install.sh
sudo journalctl -u schoolringer -f
```

Az eseménynapló megkülönbözteti, hogy a hangszóró nem érte el a kiírt URL-t,
vagy HTTP-n letöltötte a fájlt, de nem tudta lejátszani. Az első esetben a VM
bridged hálózata, az `/etc/default/schoolringer` `SCHOOLRINGER_HOST_IP` értéke és
a `SCHOOLRINGER_MEDIA_PORT` tűzfalszabálya ellenőrizendő.

Vendéghálózat, kliensizoláció, VLAN vagy tiltott multicast esetén az automatikus
felderítés nem működik. A program kiírja a Cast állapotváltozásokat és a
médialejátszó hibakódját, ha a receiver visszautasítja a fájlt.

## Tesztek

```bash
python -m unittest discover -v
```
