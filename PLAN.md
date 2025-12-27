## Streamlit UI Plan

1. Audit current UI behavior and data flow (review `src/gui/main_window.py` and entrypoints) to enumerate screens, widgets, and state.
2. Define Streamlit page structure and navigation (single-page vs. multipage), mapping existing UI sections to Streamlit layout blocks.
3. Implement the core Streamlit app skeleton (config, layout, sidebar controls, session state) and wire basic callbacks.
4. Port functional UI pieces in priority order (model selection, parameters, actions, output/preview) and connect to existing backend logic.
5. Add theming, validation, and UX polish; then add minimal tests or smoke checks for critical flows.
6. Update docs and run scripts to launch the Streamlit app alongside or instead of the current UI.

Notes:
- Step 1 audit: `docs/streamlit-ui-audit.md`.
- Step 2 layout mapping: `docs/streamlit-ui-structure.md`.
