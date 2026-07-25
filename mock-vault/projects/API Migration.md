# 🔌 API Migration

**Status:** Planning  
**Due:** December 2026

Moving from REST to GraphQL. Affects [[Website Redesign]] and [[Mobile App]].

## Why
- Over-fetching data on mobile
- N+1 query problems
- Frontend teams want flexible queries

## Plan
1. Schema design (2 weeks)
2. Apollo Server setup
3. Incremental migration (per-endpoint)
4. Deprecate old REST endpoints

## Risks
- Breaking changes for existing clients
- Learning curve for backend team
