# Detector de vehicule în intersecție — versiunea 1.5 (Piața Unirii, Iași)

Benzile și parcările camerei din Piața Unirii sunt desenate exact pe marcaje (`benzi_fixe.json`): Bulevard 2+3 benzi, Strada din dreapta 2+2 benzi.

Bazată pe versiunea 2:

În plus față de v1: sens (intră / iese din intersecție), vehicule care așteaptă să intre, benzi învățate automat (B1 = lângă bordură), numărare pe bandă și tip, salvată pe minut în CSV, ID-uri 1–1000 refolosite.


Program Python care se uită **live la ecran** (de exemplu la o cameră web dintr-o intersecție) și desenează peste imagine conturul fiecărui vehicul:

- **verde**: mașină în mișcare, cu săgeată pentru direcție
- **roșu**: mașină **oprită pe drum** (semafor, coadă), cu numărul de secunde de când stă
- **albastru**: autobuz
- **mov**: tramvai
- **gri punctat**: parcată, ignorată la numărătoare

Un panou mic arată câte vehicule sunt în mișcare sau oprite și în ce direcții merg.

## Cum funcționează

- **Detecție + segmentare:** [YOLOE](https://docs.ultralytics.com/models/yoloe/) cu cuvintele `car, van, truck, bus, tram, motorcycle`, deci recunoaște direct tramvaiele.
- **Urmărire:** fiecare vehicul primește un ID afișat (#12), stabil la pierderi scurte; chenarele duble pe același vehicul se unesc, iar starea (în mișcare / oprit) și direcția se calculează din deplasarea lui în ultimele 2 secunde.
- **Harta drumului, per cameră:** programul recunoaște camera după amprenta imaginii (contururile statice) și învață separat, pentru fiecare cameră, pe unde circulă vehiculele (folderul `harti/`). Un vehicul oprit pe drum contează. Unul oprit în afara drumului, sau nemișcat mai mult de 2 minute, e considerat parcat.
- **Optimizări:** rezoluție adaptivă (țintă 8 cadre/s), analiză doar pe zona cu drum, OpenVINO automat (alege placa video Intel sau procesorul), FP16 pe plăci NVIDIA.
- **Overlay:** o fereastră transparentă prin care poți da click, exclusă din propria captură de ecran (Windows 10 2004+ / 11).

## Instalare (Windows)

1. Python 3.11+ de pe [python.org](https://www.python.org/downloads/).
2. Dublu-click pe `instalare.bat`.
3. Opțional, dacă ai placă NVIDIA: `instalare_gpu_nvidia.bat`.

## Utilizare

```
porneste.bat                                  # live, contururi peste ecran
configureaza.bat                              # alegi zona de ecran cu camera
porneste.bat --mod fereastra                  # rezultatul într-o fereastră separată
porneste.bat --video clip.mp4 --salveaza out.mp4
porneste.bat --parcat-dupa 180                # secunde nemișcat până devine "parcat"
porneste.bat --reseteaza-harta                # reînvață drumul pentru camera curentă
```

Alte detalii (în română) găsești în `CITESTE-MA.txt`.
