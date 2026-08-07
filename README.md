# SchoolRinger

Helyi webes lejátszási rend Google Home speaker grouphoz. A felületen
tetszőleges számú heti időzítés hozható létre, napokkal, óra-perccel,
perc:másodperc formátumú lejátszási idővel és a `media` könyvtárban található
MP3-fájlok egyikével.

## Feltételek

- Python 3.11 vagy újabb
- A futtató gép és a Google Home eszközök ugyanazon a helyi hálózaton legyenek
- A kliens tűzfala engedje az mDNS UDP 5353-at és a Python bejövő kapcsolatait
- A Google Home alkalmazásban már létezzen a megcélzott speaker group

> A GitHub Codespaces nem látja az otthoni hálózat Cast eszközeit. Az alkalmazást
> azon a helyi gépen kell futtatni, amely ugyanarra a Wi-Fi/LAN hálózatra
> csatlakozik, mint a Google Home hangszórók.

## Telepítés

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

A fejlécben az automatikusan felderített speaker groupok és önálló Cast
hangszórók közül választható céleszköz. A felületből létrehozható, szerkeszthető,
kapcsolható és törölhető minden heti időzítés. A **Próba** művelet azonnal
elindítja a kiválasztott MP3-at; aktív lejátszáskor az eseménypanelen megjelenő
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

Vendéghálózat, kliensizoláció, VLAN vagy tiltott multicast esetén az automatikus
felderítés nem működik. A program kiírja a Cast állapotváltozásokat és a
médialejátszó hibakódját, ha a receiver visszautasítja a fájlt.

## Tesztek

```bash
python -m unittest discover -v
```
