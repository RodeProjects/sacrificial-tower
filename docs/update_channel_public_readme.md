# Sacrificial Tower – Windows Downloads for 3D Printing Cooling Towers

Sacrificial Tower is a free Windows 3D printing sacrificial tower tool and
G-code analyzer for minimum layer time cooling optimization. It analyzes local
print data and generates an additional printable cooling tower, automatically
or through a manual editor, to give short FDM/FFF layers more cooling time.

**Deutsch:** Sacrificial Tower analysiert Schichtzeiten und erstellt zusätzliche
Kühltürme für den FDM-/FFF-3D-Druck. Dieser öffentliche Kanal enthält die
Windows-Installer und die Daten für automatische Programmaktualisierungen.

## Download and setup

1. Open the [latest Windows release](https://github.com/RodeProjects/sacrificial-tower-updates/releases/latest).
2. Read the release notes. Current versions are **development releases for testing and evaluation**.
3. Install a supported slicer and configure your printer, filament and process profiles there.
4. Install Sacrificial Tower, select an STL and confirm the saved slicer profiles.

Supported integrations: **Anycubic Slicer Next, Bambu Studio, PrusaSlicer and
OrcaSlicer**. The exact tested versions and verification scope are maintained
with the [main project documentation](https://github.com/RodeProjects/sacrificial-tower).
The main repository currently requires access; this download channel is public.

## What is in this repository?

This repository distributes Windows installers, release notes and the
machine-readable `latest.json` for automatic program updates. End users need
no GitHub account or private source-repository credentials to download them.
The application checks the signed update manifest and the installer's size
and SHA-256 before accepting an automatic update.

## Project and license

RodeProjects develops Sacrificial Tower and offers official downloads free of charge.
The current development tree has adopted Apache License 2.0 for original code,
documentation and project-owned assets, unless otherwise noted. Future releases
built from this tree permit commercial use, modification and redistribution under
Apache-2.0, without a Commons Clause. License and attribution obligations apply;
third-party components retain their own licenses. Previously published downloads
retain the license shipped with each version; this text does not replace their
license or installer. Permitted generated results may be used commercially.
New packages built from the Apache-2.0 source tree include LICENSE.md, NOTICE,
terms, privacy information and third-party notices.
See the [main project](https://github.com/RodeProjects/sacrificial-tower)
for development sources when access is available.
