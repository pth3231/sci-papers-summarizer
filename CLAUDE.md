# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A RAG-based tool that summarizes scientific papers into bullet points, built for intensive thesis-related reading. The intended pipeline (see README.md and assets/image.png):

1. **Ingest**: upload documents to a FastAPI server → parse to readable format (marker) → chunk → embed → store in a VectorDB
2. **Retrieve & Generate**: embed the user's question → similarity search in VectorDB → combine relevant chunks with the prompt → LLM (OpenRouter, `google/gemma-4-26b-a4b-it:free`) → stream the answer back to the UI

Planned tech: FastAPI backend, marker for PDF conversion, streamed responses to the frontend.

## Current state

Early stage. `src/controllers/` and `src/models/` are empty placeholders for the FastAPI backend; `src/view/` is a stock React + Vite template (App.tsx is empty). No test framework is configured yet.

## Commands

All frontend commands run from `src/view/` (npm):

- `npm run dev` — Vite dev server with HMR
- `npm run build` — type-checks (`tsc -b`) then builds; type errors fail the build
- `npm run lint` — ESLint over the whole frontend
- `npm run preview` — serve the production build

## Structure

- `src/view/` — React 19 + TypeScript frontend (Vite 8, ESLint 10 flat config in eslint.config.js). Entry: `src/view/src/main.tsx` → `App.tsx`.
- `src/controllers/`, `src/models/` — reserved for the FastAPI backend (MVC-style split).
