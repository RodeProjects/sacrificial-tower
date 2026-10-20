# Auffindbarkeit von Sacrificial Tower in Suchmaschinen und KI-Suche

Stand: 20.10.2026. Ziel ist, Zweck, Plattform, Eingaben, Ausgaben, Grenzen und
getestete Slicer für Menschen und Suchsysteme klar zu beschreiben. Verwendete
Begriffe sind unter anderem „3D printing sacrificial tower tool“, „minimum layer
time cooling optimizer“, „G-code analyzer“, Kühlturm und minimale Schichtzeit.
Sie stehen im fachlichen Zusammenhang mit den tatsächlichen Funktionen.

## Sichtbare Projektinhalte

- Die [README](../README.md) beschreibt den Nutzen auf Deutsch und Englisch,
  enthält offizielle Downloadlinks, die getesteten Slicerversionen, Voraussetzungen,
  einen kurzen Bedienungsablauf, konkrete Funktionen und häufige Fragen.
- Die [englische FAQ](faq.md) beantwortet Fragen zu Schichtzeit, Kühltürmen,
  STL/G-Code, 3MF-Export, Profilen, Stützen, lokalen Dateien und Nutzungsrechten.
  Fachliche Details werden über beschreibende interne Links erschlossen.
- Der [Dokumentationsindex](README.md) verbindet diese Einstiege mit den
  maßgeblichen Themen. Versionsnachweise stehen unter
  [Slicer-Unterstützung](slicer_detection_modules.md#zuletzt-erfolgreich-getestete-versionen).
- Künftige, ausdrücklich beauftragte Releases erhalten über
  `scripts/publish_update.ps1` eine verständliche Produktbeschreibung in ihren
  Release Notes. Die Kennzeichnung als Entwicklungsversion bleibt erhalten.

## GitHub-Metadaten

Die Beschreibungen und Topics werden direkt in GitHubs „About“-Bereich gepflegt.
Sie sind keine aus einer Markdown-Datei automatisch übernommenen Einstellungen.
Der Projektlink beider Repositories führt zum öffentlichen Windows-Download:
`https://github.com/RodeProjects/sacrificial-tower-updates/releases/latest`.

Haupt-Repository `RodeProjects/sacrificial-tower`:

> Free Windows 3D printing sacrificial tower tool and G-code analyzer for minimum layer time cooling optimization. Supports Anycubic Slicer Next, Bambu Studio, PrusaSlicer and OrcaSlicer; STL/3MF export.

Topics: `3d-printing`, `fdm`, `fff`, `sacrificial-tower`, `cooling-tower`,
`minimum-layer-time`, `gcode`, `gcode-analysis`, `stl`, `3mf`, `orcaslicer`,
`prusaslicer`, `bambu-studio`, `anycubic-slicer-next`, `windows`.

Öffentlicher Updatekanal `RodeProjects/sacrificial-tower-updates`:

> Official Windows downloads and signed updates for Sacrificial Tower, a free 3D printing cooling tower generator and G-code analyzer for minimum layer time optimization.

Topics: `3d-printing`, `sacrificial-tower`, `cooling-tower`, `minimum-layer-time`,
`gcode-analysis`, `windows`, `windows-installer`, `software-updates`.

Die [vorbereitete öffentliche Download-README](update_channel_public_readme.md)
ist eine Fassung für das separate Update-Repository. Sie wird hier lokal gepflegt;
ihre Übernahme dort erfordert einen eigenen Commit/Push-Auftrag. Diese Aufgabe
ändert weder vorhandene öffentliche Releases noch `latest.json` oder Installer.

## Sichtbarkeit und Pflege

Das Haupt-Repository bleibt privat, bis der Benutzer ausdrücklich seine
Veröffentlichung beauftragt. Private Inhalte sind für normale öffentliche
Suchmaschinen nicht erreichbar. Der bestehende öffentliche Updatekanal bleibt
der erreichbare Download-Einstieg. Nach einer autorisierten Veröffentlichung
die sichtbaren Texte, Downloadlinks, getesteten Versionen und Lizenzangaben
aufeinander abstimmen und Verweise auf erforderlichen Repositoryzugriff entfernen.

GitHub rendert die Markdown-Seiten selbst. Eigene HTML-Metatags, Canonical-Tags,
robots.txt oder eine Sitemap in diesem Quellcode-Repository konfigurieren nicht
die Suchmaschinen-Metadaten von `github.com`. Solche Maßnahmen sind erst bei
einer tatsächlich betriebenen eigenen Website gesondert zu prüfen.

Google nennt die üblichen SEO-Grundlagen auch für generative Suchfunktionen.
Spezielle KI-Dateien wie `llms.txt` sind hierfür nicht erforderlich. Hilfreiche,
zugängliche Inhalte und nachvollziehbare Aussagen sind die Grundlage; konkrete
Indexierung, Positionen oder Empfehlungen einzelner KI-Systeme sind nicht garantiert.

Quellen, geprüft am 20.10.2026:

- [Google: Generative AI search guidance](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide)
- [Google: SEO Starter Guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)
- [GitHub: Repository README](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
- [GitHub: Repository topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)
