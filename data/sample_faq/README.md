# Sample FAQ data

This folder contains **synthetic FAQ data for a fictional company, "Acme Services"**.
It exists so a reviewer can stand up the RAG pipeline without access to a real
knowledge base.

## Contents

- `acme_services.json` — 12 chunks across 10 service categories. Schema matches
  what the FAQ ingestion pipeline writes to the MongoDB `faq_update_doc`
  collection (one document per service, with `chunks: list[dict]`).

## How to use

In production this repo ingests FAQs from a Google Sheets source via
`modules/faq_automation/`, then rebuilds the Chroma vector store from the
resulting Mongo `faq_update_doc` collection.

For demo / portfolio use:

1. Load `acme_services.json` into your local Mongo `faq_update_doc`
   collection (one document per service object). See the schema in
   `modules/faq_automation/faq_repo.py:FAQRepo.upsert_service`.
2. Run `POST /rag-assistant/knowledgebase-rebuild` (auth required — see
   `.env.example`) — this rebuilds the Chroma store from Mongo.
3. The chatbot at `/rag-assistant/chatbot/claude4sonnet` will retrieve from
   the new vector store.

## Disclaimer

All service descriptions, contact details, and phone numbers are placeholders.
This file does not represent any real organisation.
