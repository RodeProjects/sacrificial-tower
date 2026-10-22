# Sacrificial Tower FAQ: cooling towers and minimum layer time

## What is Sacrificial Tower?

Sacrificial Tower is a free Windows application that creates cooling towers for
FDM/FFF 3D printing. A tower is printed alongside your model to add time before
the next layer, helping the model cool when layer times would otherwise be too short.
Automatic mode calculates and tests a tower for your desired minimum layer
time; manual mode lets you shape the tower yourself and check the resulting
layer times. Both modes export a 3MF project containing your model and tower,
plus a separate tower STL. RodeProjects develops the application.
The [main README](../README.md) contains downloads, setup and the supported slicers.

## How does a sacrificial cooling tower help with minimum layer time?

Printing an additional object adds toolpath time before the printer returns
to the next layer of the original model. Sacrificial Tower uses the selected
printer, process and filament profiles to evaluate that extra time. Automatic
generation searches for a suitable tower; manual generation keeps the edited
shape fixed and reports the measured timing. The result depends on the actual
profiles, printer, material and cooling settings.
How closely an automatically generated tower matches your desired layer time
depends substantially on the profiles selected in the application and their settings.
The target is evaluated from slicer output; actual cooling and print quality
also depend on conditions at the printer. The extra object uses additional
material and printing time.

## Which slicers and versions are supported?

Anycubic Slicer Next, Bambu Studio, PrusaSlicer and OrcaSlicer have supported
integrations. See the [tested-version table and verification scope](slicer_detection_modules.md#zuletzt-erfolgreich-getestete-versionen).
Other slicers are excluded from installation discovery. Tests of particular
versions and profiles do not establish compatibility with every other version.

## Do I need to install and configure a slicer?

The STL workflow needs a supported local slicer with your printer configured. The
application can detect installations or accept a manually selected slicer EXE.
Select the slicer and confirm your settings in Sacrificial Tower before starting.
Existing text G-code can be evaluated separately for layer timing through the
[command-line interface](../README.md#kommandozeile).

## Does the graphical interface accept STL or G-code?

The graphical interface starts with an STL model. After model validation and
profile confirmation, it creates an isolated source slice for timing analysis.
Existing text G-code is handled by the separate CLI. Internal analysis requests
textual G-code from the slicer; binary Prusa G-code is not an analysis input.

## What can I export?

With an STL model and any of the four supported slicers, both automatic and
manual mode export a native 3MF project containing the model and tower. The tower
STL is saved alongside it. Reports describe the measured times and any simulated
settings. Open the 3MF in the selected slicer and check the final arrangement and
settings before printing. See [export and source workflow](source_workflow.md).

## Does the cooling tower replace model supports?

The original model still needs appropriate support where its geometry requires
it. Empty sliced layers can occur even in a closed STL when very thin regions
do not produce printable paths. The application reports recognized empty-layer
evidence and can offer source-specific support simulation when the selected
profile has supports globally disabled.

## Does it change my original STL or slicer profiles?

Original models and slicer-owned files remain read-only. Temporary profile
copies and generated files are created in application-owned working directories.
Model processing takes place locally. See [file safety and source analysis](source_workflow.md).

## Is Sacrificial Tower free or open source?

The current source tree uses the OSI-approved [Apache License 2.0](../LICENSE.md)
for original code, documentation and project-owned assets, unless otherwise noted.
It allows commercial use, modification and redistribution, including selling
copies and derivative versions, subject to its license and notice obligations.
There is no Commons Clause and no requirement to publish your changes.
Third-party components retain their own licenses. Permitted generated results
may also be used commercially. The provider offers official downloads free of charge;
previous releases retain their shipped license. Public release of the source
repository is a separate, planned step.

## Where can I download the Windows application?

Use the [official Windows release channel](https://github.com/RodeProjects/sacrificial-tower/releases/latest).
Current releases are development versions for testing and evaluation. The
download channel contains installers and update metadata; development sources
belong to the separate main repository.
