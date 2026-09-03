# Filament Analyzer — Documentation

## What it does

1. You upload a photo of a filament spool (or its label) in the add-on's
   ingress panel.
2. The image is sent to the configured AI provider, which extracts the spool
   properties it can read: vendor, material, colour, net weight, spool weight,
   filament diameter, and recommended print/bed temperatures.
3. Barcodes and QR codes found on the image are decoded and used as extra hints.
4. The result is matched against the public SpoolmanDB filament catalogue where
   possible, so an existing filament definition is reused instead of creating a
   duplicate.
5. You review and correct the values, then the add-on creates the filament and
   the spool in your Spoolman instance through its API.

## Installation

Add `https://github.com/schmacka/homeassistant-addons` as an add-on repository
in Home Assistant, then install **Filament Analyzer**.

No pre-built container image is published for this add-on yet, so Home
Assistant builds it locally the first time you install it. Expect the first
install to take several minutes.

## Supported architectures

The add-on supports `amd64` and `aarch64` only.

32-bit ARM (`armv7`) is not supported. The add-on runs on Alpine, and four of
its dependencies — `jiter` (pulled in by `anthropic`), `uvloop`, `httptools`
and `watchfiles` (pulled in by `uvicorn[standard]`) — publish no musl wheels
for that architecture. Installing them would mean compiling C and Rust
extensions on the device, which is slow at best and usually fails outright.

If you run Home Assistant on a Raspberry Pi 3 or newer, use the 64-bit
Home Assistant OS image; it reports as `aarch64` and is supported.

## Configuration

Example configuration:

```yaml
spoolman_url: "http://homeassistant.local:7912"
ai_provider: "anthropic"
anthropic_api_key: "sk-ant-..."
openrouter_api_key: ""
openrouter_model: "anthropic/claude-haiku-4-5"
spoolman_api_key: ""
```

### Option: `spoolman_url` (required)

Base URL of your Spoolman instance, for example
`http://homeassistant.local:7912`. If you run Spoolman as another Home
Assistant add-on, use the host and port it exposes.

### Option: `ai_provider` (required)

Which provider analyzes the uploaded images. One of:

- `anthropic` — call the Anthropic API directly. Requires
  `anthropic_api_key`.
- `openrouter` — call a model through OpenRouter. Requires
  `openrouter_api_key`, and optionally `openrouter_model`.

### Option: `anthropic_api_key`

API key used when `ai_provider` is `anthropic`. Create one at
<https://console.anthropic.com>.

### Option: `openrouter_api_key`

API key used when `ai_provider` is `openrouter`. Create one at
<https://openrouter.ai/keys>.

### Option: `openrouter_model`

Model identifier passed to OpenRouter, for example
`anthropic/claude-haiku-4-5` or `google/gemini-flash-1.5`. Only used when
`ai_provider` is `openrouter`. Defaults to `anthropic/claude-haiku-4-5`.

### Option: `spoolman_api_key`

Optional. Set this only if your Spoolman instance requires authentication.
Leave empty otherwise.

## Usage

1. Start the add-on and open it from the Home Assistant sidebar (it uses
   ingress, so no port needs to be exposed).
2. Upload one or more spool photos.
3. Check the extracted values on the review screen and fix anything the AI got
   wrong.
4. Confirm to create the filament and spool in Spoolman.

Settings can also be reviewed and adjusted at runtime on the add-on's
**Settings** page.

## Network and data

- Uploaded images are sent to the AI provider you configure. Do not upload
  images you do not want to share with that provider.
- API keys are read from the add-on options and are only used to talk to the
  configured provider and to your Spoolman instance.
- Add-on state is stored under `/data` inside the add-on container.

## Troubleshooting

**The add-on cannot reach Spoolman.** Check `spoolman_url` from the add-on's
point of view — `localhost` refers to the add-on container, not to the Home
Assistant host. Use the host name or IP of the machine running Spoolman.

**Analysis fails with an authentication error.** Verify that the API key
matching the selected `ai_provider` is set, and that the key is still valid.

**A label is not recognised.** Photograph the label straight on, in even
lighting, filling most of the frame. Values can always be corrected manually on
the review screen before the spool is created.

## Support

Report problems at
<https://github.com/schmacka/Spoolman-Importer/issues>.
