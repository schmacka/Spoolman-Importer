# Filament Analyzer

Analyze 3D printer filament spool photos with AI and add the resulting spools to
[Spoolman](https://github.com/Donkie/Spoolman) automatically.

Take a picture of a spool label, upload it through the add-on's Home Assistant
panel, review what the AI extracted (vendor, material, colour, weight, diameter,
temperatures) and push it into Spoolman with one click. Barcodes and QR codes on
the label are decoded as well, and known filaments are matched against the
public SpoolmanDB catalogue.

## Installation

1. Add the add-on repository to Home Assistant:
   `https://github.com/schmacka/homeassistant-addons`
2. Install **Filament Analyzer** from the add-on store.
3. Configure `spoolman_url` and an AI provider API key (see
   [DOCS.md](DOCS.md)).
4. Start the add-on and open it from the sidebar.

The add-on has no pre-built image; Home Assistant builds it locally on first
install, which can take a few minutes.

## Configuration

See [DOCS.md](DOCS.md) for the full option reference.

## Support

Issues and feature requests:
<https://github.com/schmacka/Spoolman-Importer/issues>
