#!/usr/bin/with-contenv bashio

export SPOOLMAN_URL=$(bashio::config 'spoolman_url')
export ANTHROPIC_API_KEY=$(bashio::config 'anthropic_api_key')
export SPOOLMAN_API_KEY=$(bashio::config 'spoolman_api_key')

bashio::log.info "Starting Filament Analyzer"
bashio::log.info "Spoolman URL: ${SPOOLMAN_URL}"

exec uvicorn app.main:app --host 0.0.0.0 --port 8080
