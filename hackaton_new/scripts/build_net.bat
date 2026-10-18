@echo off
rem Builds the Piata Unirii SUMO networks (Windows twin of scripts/build_net.sh, PLAN.md section 6).
rem   scripts\build_net.bat         sumo/net.net.xml (static program) + sumo/net_actuated.net.xml
rem   scripts\build_net.bat --osm   additionally sumo/net_osm_raw.net.xml, the raw OSM import (reference only)
setlocal
cd /d "%~dp0.."
call scripts\env.bat || exit /b 1
set "NETCONVERT=%SUMO_HOME%\bin\netconvert.exe"
set COMMON=--node-files sumo/src/piata_unirii.nod.xml --edge-files sumo/src/piata_unirii.edg.xml --type-files sumo/src/piata_unirii.typ.xml --no-turnarounds --crossings.guess --walkingareas --tls.yellow.time 3 --tls.cycle.time 90 --tls.left-green.time 6 --junctions.corner-detail 5 --offset.disable-normalization

"%NETCONVERT%" %COMMON% --tls.default-type static -o sumo/net.net.xml || exit /b 1
python scripts\tune_tls.py sumo/net.net.xml || exit /b 1
"%NETCONVERT%" %COMMON% --tls.default-type actuated -o sumo/net_actuated.net.xml || exit /b 1
echo OK: sumo/net.net.xml, sumo/net_actuated.net.xml

if /i not "%~1"=="--osm" exit /b 0
"%NETCONVERT%" --osm-files sumo/map.osm -o sumo/net_osm_raw.net.xml --tls.guess-signals --tls.join --junctions.join --remove-edges.isolated --keep-edges.by-vclass passenger --no-warnings || exit /b 1
echo OK: sumo/net_osm_raw.net.xml (raw import, not used by the demo)
