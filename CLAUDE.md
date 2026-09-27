https://github.com/drajb/whisper-local

@docs/project-index.md
@docs/platform-abstraction.md

- Test app startup: `/test-from-wsl` (launch only, no interaction)
- Ask user for real test before committing
- Prefer elegant code that is modular and consistent
- Use explicit variable/function names
- **Comment generously for readability.** Every module starts with a 2–4 line header comment describing its purpose. Non-trivial functions get a one-line comment above them explaining intent (not mechanics). Group related code into labeled sections so a newcomer can follow the file top-to-bottom. Don't echo what the code obviously does ("# increment counter"); explain WHY.
- **No backward compatibility** - Break old formats freely