#!/bin/bash
# shellcheck disable=SC1091
source /usr/share/bashio/module.bash

export SPOOLMAN_URL
SPOOLMAN_URL=$(bashio::config 'spoolman_url')

export SPOOLMAN_API_KEY
SPOOLMAN_API_KEY=$(bashio::config 'spoolman_api_key' '')

AI_PROVIDER=$(bashio::config 'ai_provider')
export AI_PROVIDER

if [ "${AI_PROVIDER}" = "openrouter" ]; then
    export OPENROUTER_API_KEY
    OPENROUTER_API_KEY=$(bashio::config 'openrouter_api_key' '')
    export OPENROUTER_MODEL
    OPENROUTER_MODEL=$(bashio::config 'openrouter_model' 'anthropic/claude-haiku-4-5')
else
    export ANTHROPIC_API_KEY
    ANTHROPIC_API_KEY=$(bashio::config 'anthropic_api_key' '')
fi

bashio::log.info "Starting Filament Analyzer"
bashio::log.info "Spoolman URL: ${SPOOLMAN_URL}"
bashio::log.info "AI Provider: ${AI_PROVIDER}"

exec uvicorn app.main:app --host 0.0.0.0 --port 8080
