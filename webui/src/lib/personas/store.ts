/**
 * The personas, held once for every page that shows them: the Personas page,
 * the account cards, the scope pills on Pictures, Memory and Settings.
 */
import { api } from "../api";
import { resource } from "../resource";
import { EMPTY, type PersonaList } from "./logic";

export const personasRes = resource<PersonaList>("personas", () => api.personas(), EMPTY);

/** Asked again after a change, without the sidebar's spinner. */
export function reloadPersonas() {
  return personasRes.refresh({ force: true, quiet: true });
}
