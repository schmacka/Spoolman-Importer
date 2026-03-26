# Spoolman Importer – Filament Analyzer

Analyze 3D printer filament spool photos with AI and add spools to [Spoolman](https://github.com/Donkie/Spoolman) automatically.

## How it works

1. **Upload** a photo of a filament spool label.
2. **Claude AI** reads the label and extracts vendor, material, color, weight, and print temperatures.
3. **SpoolmanDB** enriches technical fields (density, diameter, temps) for known filaments.
4. **Review** the pre-filled form, tweak anything, then submit.
5. The spool is created in your Spoolman instance — vendor and filament records are reused if they already exist.

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env – set SPOOLMAN_URL and ANTHROPIC_API_KEY
docker compose up -d
```

Open <http://localhost:8080> in your browser.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SPOOLMAN_URL` | `http://localhost:7912` | URL of your Spoolman instance |
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key from <https://console.anthropic.com> |
| `SPOOLMAN_API_KEY` | *(empty)* | Optional Spoolman API key |

## Home Assistant add-on

The `addon/` directory contains a Home Assistant add-on. Add this repository as a custom add-on repository in the Add-on Store, then install **Filament Analyzer**.

Configure `spoolman_url` and `anthropic_api_key` in the add-on options.

## Requirements

- Python 3.12+
- An [Anthropic](https://console.anthropic.com) account with API access
- A running [Spoolman](https://github.com/Donkie/Spoolman) instance
