# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0-alpha] — 2026-03-28

### Added
- Dual-checkpoint pipeline (Control 1 + Control 2)
- IBAC authorization tuples
- Plan Review with step ordering validation
- Input sanitizer with Unicode normalization
- Session Guard with cross-iteration memory
- MCP Proxy with dynamic tool discovery
- LLM provider abstraction (OpenAI, Anthropic, Ollama)
- Python SDK with FastAPI middleware
- HR Assistant demo app
- 148 tests across 15 layers

### Known limitations
- No persistent audit log (in-memory only)
- No authentication / multi-user support
- No dashboard UI
- Local models (Ollama) have lower parsing accuracy
