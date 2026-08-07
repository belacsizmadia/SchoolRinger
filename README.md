# SchoolRinger POC

Parancssori proof of concept, amely egy helyi `teszt.mp3` fájlt játszik le egy
Google Home speaker groupon. A program:

1. mDNS-en felderíti a helyi hálózat Cast eszközeit;
2. csak a Google Cast group típusú célokat kínálja fel;
3. ideiglenes HTTP-szerveren elérhetővé teszi az MP3-at;
4. elindítja a Default Media Receiveren a lejátszást.

## Feltételek

- Python 3.11 vagy újabb
- A futtató gép és a Google Home eszközök ugyanazon a helyi hálózaton legyenek
- A kliens tűzfala engedje az mDNS UDP 5353-at, valamint a program által kiírt
  ideiglenes TCP portot
- A projekt gyökerében legyen egy lejátszható `teszt.mp3`

> A GitHub Codespaces nem látja az otthoni hálózat Cast eszközeit. Ezt a POC-ot
> azon a helyi gépen kell futtatni, amely ugyanarra a Wi-Fi/LAN hálózatra
> csatlakozik, mint a Google Home hangszórók.

## Telepítés és futtatás

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python schoolringer.py --list
python schoolringer.py --group "Iskola"
```

A `--group` elhagyásakor a program interaktívan kér csoportválasztást. További
kapcsolók:

```bash
python schoolringer.py --help
python schoolringer.py --group "Iskola" --file masik.mp3 --port 8080
python schoolringer.py --group "Iskola" --host-ip 192.168.1.20
```

A `--host-ip` akkor hasznos, ha a gépnek több hálózati interfésze van, és az
automatikusan választott IP-cím nem érhető el a hangszórókról. A program addig
szolgálja ki a fájlt, amíg a lejátszás fut; `Ctrl+C` leállítja a Cast sessiont.

## Korlátok

Ez helyi hálózati POC, nem ütemező és nem felhőszolgáltatás. A speaker groupnak
a Google Home alkalmazásban már léteznie kell. Vendéghálózat, kliensizoláció,
VLAN-ok vagy tiltott multicast esetén az automatikus felderítés nem működik.
