// Public API of the conversations feature (design D1). `app/` composes this entry
// point; the data source, hooks, store, pure logic and the panel components stay
// private, which `eslint.config.mjs` enforces.
export { ConversationsView } from "./components/conversations-view";
